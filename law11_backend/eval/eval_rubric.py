#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_rubric.py
──────────────
답변을 **항목별로** 채점한다 (로드맵 P2).

기존 지표는 답변 하나에 점수 하나를 준다 — RAGAS Faithfulness가 0.74면
"무엇이 부족한지"를 말해주지 않고, 할루시네이션 판정은 "없는 내용을 더했는가"
한 축만 본다. 실제로 #72의 결함(처벌 분기 조건이 사라진 것)은 **사람이 답변을
읽어서** 찾았고, 두 지표 모두 그걸 가리키지 못했다.

그래서 질문 유형별 rubric을 정의하고 항목마다 독립 판정한다. 산출물은 평균
점수가 아니라 **어느 항목이 깎였는지**다.

실행:
    cd law11_backend
    python -m eval.eval_rubric                            # 최신 baseline 채점
    python -m eval.eval_rubric --result <path.json>       # 특정 결과 파일
    python -m eval.eval_rubric --case GS-023 --repeat 3   # 특정 케이스만 3회
"""

import re
import sys
import json
import asyncio
import argparse
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings

EVAL_DIR    = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)
GOLDEN_PATH = EVAL_DIR / "golden_dataset.json"

SCORE = {"충족": 1.0, "부분충족": 0.5, "미충족": 0.0}
# 조문이 그 항목을 규정하지 않아 **채점 자체가 성립하지 않는** 경우. 평균에서 빼며
# 0점으로 세지 않는다 — 실측(#80 1차): 조문에 수치가 아예 없는 GS-017·GS-018이
# `수치 기준 미충족`을 받아 standard 유형 평균을 0.444로 끌어내렸다. 조문에 없는 것을
# 답변이 빠뜨렸다고 감점하는 것은 채점 규칙 위반인데, 판정 어휘에 그 선택지가
# 없으면 채점기는 미충족을 고른다.
NOT_APPLICABLE = "해당없음"

# ─────────────────────────────
# 질문 유형별 rubric
#
# 항목은 **답변을 읽고 사람이 판단하던 것**을 글로 옮긴 것이다. 특정 케이스의
# 정답(조문 문구)을 적지 않는다 — 그건 채점기에 답을 가르치는 것이고, 그렇게
# 얻은 점수는 측정값이 아니다(#78에서 실제로 한 번 저질렀다).
#
# `분기 조건` 항목의 "조건 문구가 서로 같으면 미충족"은 #72가 손으로 찾아낸
# 결함의 **판정 기준**이다. 어느 조문인지는 적지 않는다.
# ─────────────────────────────
# 실측(#80 1차): 답변이 "산업안전보건법 제17조는 …"처럼 **산문으로** 법령명과 조문
# 번호를 밝혔는데 채점기가 "인용하지 않았다"며 깎았다(direct_article/근거 조문 0.375).
# "인용"이라는 말이 대괄호 형식을 떠올리게 한 것이다. 형식을 묻지 않는다고 못박는다.
# ── `근거 조문` 항목은 LLM에게 묻지 않는다 (#80 2차) ──
# 1차에서 criterion 문구를 고쳐도 채점기는 "산업안전보건기준에 관한 규칙 제32조는 …"을
# "조문 번호가 나타나지 않는다"며 계속 깎았다(direct_article/근거 조문 0.5). 법령명에
# **공백**이 있으면 못 읽는 것이었고, 그건 정규식 한 줄로 끝나는 판정이다. #78에서
# 판정기의 조문 대조를 코드로 떼어낸 것과 같은 처방 — 기계적으로 확인되는 항목을
# LLM에게 맡기면 틀릴 자유만 준다.
#
# ⚠️ 이 검사는 **인용이 있는지**만 본다. 인용이 **맞는지**는 보지 않는다 —
#    없는 조문(제999조)을 적어도 통과한다. 인용의 실재 여부는 `eval_hallucination`의
#    citation 검증(DB 조회)이 맡는다. 두 축을 섞지 않는다.
_ARTICLE_RE = re.compile(r"제\s*\d+(?:의\s*\d+)?\s*조")
_LAW_NAME_RE = re.compile(r"[가-힣]{2}[가-힣\s]{0,22}(?:법률|법|규칙|시행령|시행규칙)")


def citation_present(answer: str) -> Dict[str, Any]:
    """답변 본문에 법령명과 조문 번호가 함께 나타나는가 (형식 무관)."""
    art = _ARTICLE_RE.search(answer)
    law = _LAW_NAME_RE.search(answer)
    hit = bool(art and law)
    return {
        "verdict": "충족" if hit else "미충족",
        "reason": ("법령명과 조문 번호가 본문에 있다" if hit else
                   f"법령명 {'있음' if law else '없음'} · 조문 번호 {'있음' if art else '없음'}"),
        "quote": f"{law.group().strip()} {art.group()}" if hit else "",
    }


CITATION_CRITERION = (
    "답변 본문에 법령명과 조문 번호가 나타나는가. **형식은 상관없다** — "
    "`[산업안전보건법 제17조]` 같은 대괄호 표기든, \"산업안전보건법 제17조는 …\"처럼 "
    "문장 안에서 밝히든 모두 충족이다. 조문 번호가 아예 없을 때만 미충족이다."
)

RUBRICS: Dict[str, List[Dict[str, str]]] = {
    "penalty": [
        {"name": "처벌 수준", "criterion":
            "형량·벌금액을 조문에 적힌 대로 명시했는가. **제공된 조문이 형벌(징역·벌금)을 "
            "규정하지 않으면 해당없음**이다 — 손해배상·과태료처럼 형벌이 아닌 책임만 "
            "규정하는 조문에 형량을 요구하지 마라."},
        {"name": "분기 조건", "criterion":
            "처벌이 갈리는 조건을 각 결과에 붙여 구분했는가. 조문이 조건에 따라 처벌을 "
            "나누는데 답변이 조건 없이 나열했거나, 항목을 나눴는데 **항목들의 조건 문구가 "
            "서로 같다면 미충족**이다(가르는 조건이 빠진 것). 제공된 조문이 결과를 조건에 "
            "따라 나누지 않으면 해당없음이다."},
        {"name": "근거 조문", "criterion": CITATION_CRITERION, "mechanical": "citation"},
    ],
    "direct_article": [
        {"name": "조문 일치", "criterion":
            "질문이 지목한 법령·조문의 내용을 답했는가. 다른 조문의 내용으로 바꿔치지 않았는가."},
        {"name": "핵심 의무", "criterion": "그 조문이 규정하는 핵심 의무·요건을 빠뜨리지 않았는가."},
        {"name": "근거 조문", "criterion": CITATION_CRITERION, "mechanical": "citation"},
    ],
    "standard": [
        {"name": "수치 기준", "criterion":
            "조문에 있는 수치·규격 기준을 명시했는가. **제공된 조문에 수치·규격 기준이 "
            "하나도 없으면 해당없음**이다 — 조문에 없는 수치를 답변이 적지 않은 것은 감점 사유가 아니다."},
        {"name": "적용 조건", "criterion": "그 기준이 적용되는 대상·작업·상황을 밝혔는가."},
        {"name": "근거 조문", "criterion": CITATION_CRITERION, "mechanical": "citation"},
    ],
    "concept": [
        {"name": "정의", "criterion": "개념의 정의를 조문 근거로 설명했는가."},
        {"name": "실시 방법", "criterion": "무엇을 어떻게·언제 해야 하는지(절차·시기)를 밝혔는가."},
        {"name": "근거 조문", "criterion": CITATION_CRITERION, "mechanical": "citation"},
    ],
}

RUBRIC_SYSTEM = """너는 법령 질의응답 답변을 항목별로 채점하는 평가자야.

[채점 규칙]
1. 각 항목을 **독립적으로** 판정해. 다른 항목이 좋다고 이 항목을 올려주지 마.
2. 판정은 제공된 조문만 근거로 한다. 조문에 없는 것을 답변이 빠뜨렸다고 감점하지 마.
3. 판정은 세 가지뿐이다.
   충족     : 항목이 요구하는 내용이 답변에 있다
   부분충족 : 일부만 있다 (예: 수치는 있는데 적용 조건이 없다)
   미충족   : 없다
   해당없음 : **제공된 조문이 그 항목을 규정하지 않아 채점이 성립하지 않는다.**
             조문에 수치 기준이 하나도 없는데 "수치 기준" 항목을 보는 경우처럼.
             답변이 부실한 것과 조문에 그 내용이 없는 것을 섞지 마라.
4. 각 항목마다 **답변에서 그대로 복사한 문장**을 quote에 넣어 근거를 밝혀라.
   해당 내용이 답변에 없어서 미충족이면 quote는 빈 문자열로 둬.
5. 답변이 조문에 없는 내용을 더했는지는 **이 채점의 대상이 아니다**(별도 지표).
   여기서는 "요구한 항목을 갖췄는가"만 본다.

[출력 형식 - JSON 그대로]
{
  "items": [
    {"name": "항목명", "verdict": "충족|부분충족|미충족|해당없음", "reason": "한 문장", "quote": "답변에서 복사한 문장"}
  ]
}"""


def _load_types() -> Dict[str, str]:
    """골든셋에서 question → question_type 매핑.

    rubric이 없는 유형이 섞여 있으면 **여기서 터뜨린다.** 기본값으로 때우면
    골든셋에 유형을 추가했을 때 엉뚱한 rubric으로 조용히 채점된다 — 평가 도구가
    조용히 틀리는 건 이 프로젝트가 반복해서 당한 실패 양상이다(#60·#76).
    """
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    types = {c["question"]: c["question_type"] for c in data["dataset"]}
    unknown = sorted(set(types.values()) - set(RUBRICS))
    if unknown:
        raise ValueError(f"rubric이 정의되지 않은 question_type: {unknown} — RUBRICS에 추가하라")
    return types


async def score_case(question: str, answer: str, contexts: List[str],
                     rubric: List[Dict[str, str]]) -> Dict[str, Any]:
    asked = [it for it in rubric if not it.get("mechanical")]
    items_block = "\n".join(f"- {it['name']}: {it['criterion']}" for it in asked)
    ctx_block = "\n\n".join(f"[조문 {i+1}]\n{c}" for i, c in enumerate(contexts[:5]))
    user_msg = f"""[질문]
{question}

[검색된 법령 조문]
{ctx_block}

[AI 답변]
{answer}

[채점 항목]
{items_block}

각 항목을 판정해. JSON만 출력해."""

    try:
        resp = await settings.openai_client.chat.completions.create(
            # 판정기는 생성 모델과 분리해 고정한다 — 생성 모델을 바꿀 때 채점자까지
            # 바뀌면 "답변이 좋아진 것"과 "채점이 후해진 것"을 구분할 수 없다 (#57).
            model=settings.JUDGE_MODEL,
            messages=[{"role": "system", "content": RUBRIC_SYSTEM},
                      {"role": "user", "content": user_msg}],
            temperature=0,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(resp.choices[0].message.content)
    except Exception as e:
        return {"error": str(e), "items": []}

    # 채점기가 항목을 빼먹거나 지어내면 그대로 집계하지 않는다 — 요청한 항목만
    # 받고, 빠진 항목은 'ERROR'로 남겨 평균에서 제외한다.
    by_name = {i.get("name"): i for i in parsed.get("items", []) if isinstance(i, dict)}
    items = []
    for it in rubric:
        if it.get("mechanical") == "citation":
            # 채점기가 이 항목을 돌려줬어도 무시한다 — 기계 판정이 기준이다.
            items.append({"name": it["name"], **citation_present(answer)})
            continue
        got = by_name.get(it["name"], {})
        raw = got.get("verdict")
        verdict = raw if raw in SCORE or raw == NOT_APPLICABLE else "ERROR"
        items.append({
            "name":    it["name"],
            "verdict": verdict,
            "reason":  got.get("reason", "채점기가 이 항목을 판정하지 않았다"),
            "quote":   got.get("quote", ""),
        })
    scored = [SCORE[i["verdict"]] for i in items if i["verdict"] in SCORE]
    return {"items": items, "score": round(sum(scored) / len(scored), 3) if scored else None}


async def run(result_path: Optional[str] = None, only_case: Optional[str] = None,
              sample: Optional[int] = None) -> Optional[Dict[str, Any]]:
    path = Path(result_path) if result_path else max(
        RESULTS_DIR.glob("baseline_*.json"), default=None, key=lambda p: p.name)
    if not path or not path.exists():
        print("❌ 채점할 결과 파일이 없다. 먼저 python -m eval.harness 를 실행하라.")
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    types = _load_types()
    cases = [c for c in data.get("per_case_results", [])
             if c.get("status") == "success" and c.get("contexts") and c.get("answer")]
    if only_case:
        cases = [c for c in cases if c.get("id") == only_case]
    if sample:
        cases = cases[:sample]

    print(f"\n{'='*65}\n  rubric 항목별 채점 — {path.name}\n{'='*65}")
    print(f"  대상 {len(cases)}건 · 채점 {settings.JUDGE_MODEL}\n")

    details = []
    for i, case in enumerate(cases):
        # 골든셋에 없는 질문(다른 결과 파일로 채점할 때)은 유형을 알 수 없다.
        # 그 경우만 concept로 두고 표에 그대로 드러나게 한다.
        qtype = types.get(case["question"], "concept")
        rubric = RUBRICS[qtype]
        print(f"  [{i+1:02d}/{len(cases)}] {case.get('id','?')} ({qtype}) ...", end=" ", flush=True)
        res = await score_case(case["question"], case["answer"], case["contexts"], rubric)
        marks = "".join({"충족": "●", "부분충족": "◐", "미충족": "○", NOT_APPLICABLE: "–"}.get(it["verdict"], "?")
                        for it in res["items"])
        print(f"{marks}  {res.get('score')}")
        details.append({"id": case.get("id", f"#{i+1}"), "question_type": qtype,
                        "question": case["question"], **res})
        await asyncio.sleep(0.3)

    # 항목별 집계 — 이 표가 이 평가의 산출물이다. 평균 점수 하나로 뭉개지 않는다.
    per_item = defaultdict(list)
    na_count = defaultdict(int)
    for d in details:
        for it in d["items"]:
            if it["verdict"] in SCORE:
                per_item[(d["question_type"], it["name"])].append(SCORE[it["verdict"]])
            elif it["verdict"] == NOT_APPLICABLE:
                na_count[(d["question_type"], it["name"])] += 1

    print(f"\n{'─'*65}\n  {'유형':<16}{'항목':<12}{'평균':>7}{'  충족/부분/미충족':>18}")
    print(f"  {'─'*61}")
    for (qtype, name), vals in sorted(per_item.items()):
        full = sum(1 for v in vals if v == 1.0)
        part = sum(1 for v in vals if v == 0.5)
        miss = sum(1 for v in vals if v == 0.0)
        na = na_count.get((qtype, name), 0)
        print(f"  {qtype:<16}{name:<12}{sum(vals)/len(vals):>7.2f}{f'{full}/{part}/{miss}':>18}"
              + (f"   (해당없음 {na})" if na else ""))

    scores = [d["score"] for d in details if d["score"] is not None]
    overall = round(sum(scores) / len(scores), 3) if scores else None
    print(f"  {'─'*61}\n  전체 평균 {overall}  ({len(scores)}건)")

    weak = [(d["id"], it["name"], it["reason"]) for d in details for it in d["items"]
            if it["verdict"] == "미충족"]
    if weak:
        print(f"\n  ── 미충족 항목 {len(weak)}건 ──")
        for cid, name, reason in weak:
            print(f"  [{cid}] {name}: {reason[:80]}")
    print(f"{'─'*65}\n")

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source":       path.name,
        "judge_model":  settings.JUDGE_MODEL,
        "overall":      overall,
        "per_item":     {f"{q}/{n}": round(sum(v)/len(v), 3) for (q, n), v in per_item.items()},
        "not_applicable": {f"{q}/{n}": c for (q, n), c in na_count.items()},
        "details":      details,
    }
    suffix = "" if path.name.startswith("baseline_") else f"_{path.stem}"
    if only_case:
        suffix += f"_{only_case}"
    out_path = RESULTS_DIR / f"rubric_report{suffix}.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장 완료 → {out_path}\n")
    return output


async def run_repeat(repeat: int, **kwargs) -> None:
    """같은 입력 N회. 항목 판정이 회차마다 뒤집히면 그 항목은 아직 측정이 아니다."""
    runs = []
    for i in range(repeat):
        print(f"\n{'='*65}\n  {i+1}/{repeat} 회차\n{'='*65}")
        out = await run(**kwargs)
        if not out:
            return
        runs.append(out)

    print(f"\n{'─'*65}\n  반복 채점 요약 — 같은 입력 {repeat}회\n{'─'*65}")
    print(f"  전체 평균: {[r['overall'] for r in runs]}")
    keys = sorted({k for r in runs for k in r["per_item"]})
    flipped = []
    for k in keys:
        vals = [r["per_item"].get(k) for r in runs]
        if len({v for v in vals if v is not None}) > 1:
            flipped.append((k, vals))
    if flipped:
        print("\n  회차마다 달라진 항목 (판정 불안정):")
        for k, vals in flipped:
            print(f"    {k:<32} {vals}")
    else:
        print("\n  모든 항목이 3회 동일 — 항목 판정이 재현된다.")
    print(f"{'─'*65}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", type=str, default=None)
    ap.add_argument("--case", type=str, default=None, help="특정 케이스 id만 채점")
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    kwargs = {"result_path": a.result, "only_case": a.case, "sample": a.sample}
    if a.repeat > 1:
        asyncio.run(run_repeat(a.repeat, **kwargs))
    else:
        asyncio.run(run(**kwargs))
