#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_hallucination.py
──────────────────────
GPT 답변이 검색된 조문(context)에 근거하는지 LLM-judge 방식으로 검사한다.

판정 기준:
  - GROUNDED   : 답변의 모든 구체적 주장이 제공된 조문에서 확인 가능
  - PARTIAL    : 일부 주장은 조문 기반, 일부는 조문 외 내용
  - HALLUCINATION: 조문에 없는 수치·조건·사실을 주장

실행:
    cd law11_backend
    source .venv/bin/activate
    python -m eval.eval_hallucination                       # 최신 run_eval 결과 사용
    python -m eval.eval_hallucination --result <path.json>  # 특정 결과 파일 지정
    python -m eval.eval_hallucination --sample 5            # 빠른 테스트
    python -m eval.eval_hallucination --repeat 3            # 같은 입력 3회 — 판정 흔들림 확인
"""

import re
import sys
import asyncio
import argparse
import json
from collections import Counter
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings

EVAL_DIR    = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

JUDGE_SYSTEM = """너는 RAG 시스템의 할루시네이션을 탐지하는 전문 평가자야.

[작업]
제공된 '법령 조문'과 'AI 답변'을 비교해서 답변이 조문에 근거하는지 판정해.

[판정 기준]
GROUNDED      : 답변의 구체적 주장(수치, 조건, 의무)이 모두 조문에서 확인 가능
PARTIAL       : 일부는 조문 기반, 일부는 조문에 없는 내용 포함
HALLUCINATION : 조문에 없는 수치, 기간, 조건, 처벌 내용을 주장

[판정 규칙 — 반드시 지켜]
1. 문제를 지적하려면 그 문장을 답변에서 **그대로 복사**해 suspicious_claims에 넣어.
   답변에 없는 문장을 지어내서 지적하지 말고, 요약·의역해서 지적하지도 마.
2. 지적하기 전에 제공된 조문을 처음부터 다시 훑어봐. 그 내용이 조문 어딘가에
   있으면 지적하면 안 된다.
3. 조문 원문을 그대로 옮긴 부분은 GROUNDED다. 특히 답변이 어떤 조문의 처벌·요건을
   설명하면서 그 조문 본문에 적혀 있는 다른 조문 번호를 함께 옮겨 적은 경우
   (예: 제10조가 "제9조를 위반하여 …"라고 규정하므로 답변도 "제9조를 위반하여"라고
   쓴 경우), 그 다른 조문(제9조)의 본문이 제공되지 않았더라도 GROUNDED다.
   제공된 조문에 그 문구가 적혀 있다는 것 자체가 근거다.
   **이런 교차 참조를 이유로 PARTIAL을 주지 마.**
4. **누락은 결함이 아니다.** 조문의 일부를 설명하지 않았거나 더 자세히 쓰지 않은 건
   PARTIAL 사유가 아니다. PARTIAL/HALLUCINATION은 조문에 **없는 내용을 더한**
   경우에만 해당한다.
5. 지적할 문장이 하나도 없으면 GROUNDED다. 억지로 흠을 찾지 마.

[출력 형식 - JSON 그대로]
{
  "verdict": "GROUNDED" | "PARTIAL" | "HALLUCINATION",
  "reason": "한 문장 이유",
  "suspicious_claims": ["답변에서 그대로 복사한 문장1", "문장2"]  // PARTIAL/HALLUCINATION 시만
}"""


def _article_label(text: str) -> str:
    """조문 본문 첫머리의 '제N조'를 라벨로 뽑는다.

    ⚠️ 컨텍스트를 '[조문 1]', '[조문 2]' 같은 일련번호로만 라벨링하면, 답변이
    "제383조"라고 인용했을 때 판정기가 5개 블록 본문을 일일이 뒤져야 하고 자주
    놓친다 — 실측(2026-09-05): 제383조·제672조·제348조가 모두 검색 결과 안에
    있었는데도 "제공된 조문에 없다"며 PARTIAL로 오판했다. 라벨에 실제 조문번호를
    박아 대조 자체를 불필요하게 만든다.
    """
    m = re.match(r"\s*(제\d+조(?:의\d+)?)", text)
    return m.group(1) if m else "조문번호 미상"


async def judge_single(question: str, answer: str, contexts: List[str]) -> Dict[str, Any]:
    ctx_block = "\n\n".join(
        f"[조문 {i+1} — {_article_label(c)}]\n{c}" for i, c in enumerate(contexts[:5])
    )
    user_msg = f"""[사용자 질문]
{question}

[검색된 법령 조문]
{ctx_block}

[AI 답변]
{answer}

위 조문만을 근거로 답변이 올바른지 판정해. JSON만 출력해."""

    try:
        resp = await settings.openai_client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip()
        return json.loads(raw)
    except Exception as e:
        return {"verdict": "ERROR", "reason": str(e), "suspicious_claims": []}


def extract_cited_articles(answer: str) -> list:
    """답변에서 [법령명 제N조] 패턴 추출"""
    pattern = r"\[([^\]]+?)\s+제(\d+(?:의\d+)?)조\]"
    matches = re.findall(pattern, answer)
    return [{"law_name": m[0], "article_number": m[1]} for m in matches]


async def verify_citations(answer: str) -> dict:
    """
    답변에서 인용된 조문이 law_chunks에 실제로 존재하는지 확인.
    반환: {"verdict": "OK"|"CITATION_MISS", "missing": [...]}
    """
    cited = extract_cited_articles(answer)
    if not cited:
        return {"verdict": "OK", "missing": []}

    from sqlalchemy import text as sa_text
    from app.tools.law_rag_tool import normalize_law_name, normalize_article

    missing = []
    for c in cited:
        law_norm = normalize_law_name(c["law_name"])
        article_norm = normalize_article(c["article_number"])
        sql = sa_text("""
            SELECT 1 FROM law_chunks
            WHERE law_name_norm = :law AND article_number_norm = :article
            LIMIT 1
        """)
        try:
            async with settings.async_engine.connect() as conn:
                result = await conn.execute(sql, {"law": law_norm, "article": article_norm})
                if not result.fetchone():
                    missing.append(f"{c['law_name']} 제{c['article_number']}조")
        except Exception:
            pass

    verdict = "CITATION_MISS" if missing else "OK"
    return {"verdict": verdict, "missing": missing}


def load_latest_result() -> Optional[Dict]:
    results = sorted(RESULTS_DIR.glob("baseline_*.json"), reverse=True)
    if not results:
        return None
    with open(results[0], encoding="utf-8") as f:
        return json.load(f)


def summarize_repeat(runs: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """같은 입력 N회 판정 결과 → 케이스별 판정 이력 (#62·#71의 남은 과제).

    #72에서 배운 것: **"3회 모두 걸렸다"는 신호이지 증거가 아니다.** GS-024는
    3/3 반복됐고 실제 결함이었지만, GS-004도 3/3 반복됐고 조문 원문과 대조하니
    오탐이었다. 그래서 반복 집계의 산출물은 '율'이 아니라 케이스별 이력이다 —
    매회 지적되는 케이스(조문 대조 대상)와 회차마다 뒤집히는 케이스(판정기 자체의
    불안정)를 구분하는 것이 목적이다. temperature=0이어도 뒤집힌다.
    """
    if not runs:
        raise ValueError("회차 결과가 없다")

    by_run = [{d["id"]: d["verdict"] for d in r} for r in runs]
    if any(set(b) != set(by_run[0]) for b in by_run[1:]):
        raise ValueError("회차마다 케이스 집합이 다르다 — 같은 입력으로 반복해야 비교가 성립한다")

    ids = [d["id"] for d in runs[0]]
    per_case = {i: [b[i] for b in by_run] for i in ids}
    return {
        "runs":           len(runs),
        "verdict_counts": [dict(Counter(b.values())) for b in by_run],
        "per_case":       per_case,
        # 매회 GROUNDED가 아닌 케이스 — 조문 원문과 대조할 대상
        "always_flagged": [i for i, vs in per_case.items() if all(v != "GROUNDED" for v in vs)],
        # 회차마다 판정이 달라진 케이스 — 판정기 불안정의 직접 증거
        "flipped":        [i for i, vs in per_case.items() if len(set(vs)) > 1],
    }


def print_repeat_summary(summary: Dict[str, Any]) -> None:
    icons = {"GROUNDED": "✅", "PARTIAL": "⚠️", "HALLUCINATION": "❌", "ERROR": "💥"}
    n = summary["runs"]
    print(f"\n{'─'*65}")
    print(f"  반복 판정 요약 — 같은 입력 {n}회  (판정 {settings.LLM_MODEL}, temperature 0)")
    print(f"{'─'*65}")
    for i, counts in enumerate(summary["verdict_counts"]):
        print(f"  {i+1}회차: " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())))

    flagged, flipped = summary["always_flagged"], summary["flipped"]
    watch = [i for i in summary["per_case"] if i in set(flagged) | set(flipped)]
    print()
    if not summary["per_case"]:
        print("  판정한 케이스가 없다 — 입력 결과 파일을 확인하라.")
    elif not watch:
        print(f"  {n}회 모두 전 케이스 GROUNDED — 판정 흔들림 없음.")
    for i in watch:
        marks = "".join(icons.get(v, "?") for v in summary["per_case"][i])
        state = "매회 지적 — 조문 대조 대상" if i in flagged else "회차마다 뒤집힘 — 판정기 불안정"
        print(f"  {i:<10}{marks:<{n*3}}{state}")
    print()
    print("  매회 지적된 케이스도 신호일 뿐이다 — 반복성은 증거가 아니므로 조문 원문과")
    print("  대조해 판정한다. #72의 GS-004가 3/3 반복된 오탐이었다.")
    print(f"{'─'*65}\n")


async def run_repeat(repeat: int, result_path: Optional[str] = None,
                     sample: Optional[int] = None) -> Dict[str, Any]:
    runs = []
    for i in range(repeat):
        print(f"\n{'='*65}\n  {i+1}/{repeat} 회차\n{'='*65}")
        out = await run(result_path=result_path, sample=sample)
        if not out:
            raise RuntimeError("회차 실행이 결과를 내지 못했다 — 입력 결과 파일을 확인하라")
        runs.append(out["details"])

    summary = summarize_repeat(runs)
    print_repeat_summary(summary)

    out_path = RESULTS_DIR / "hallucination_repeat.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"),
                   "judge_model": settings.LLM_MODEL, **summary}, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료 → {out_path}\n")
    return summary


async def run(result_path: Optional[str] = None, sample: Optional[int] = None):
    print(f"\n{'='*65}")
    print(f"  할루시네이션 검사 — LLM Judge")
    print(f"{'='*65}\n")

    if result_path:
        with open(result_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = load_latest_result()

    if not data:
        print("❌ run_eval 결과 파일이 없습니다. 먼저 python -m eval.run_eval 실행하세요.")
        return

    cases = [r for r in data.get("per_case_results", [])
             if r["status"] == "success" and r.get("contexts") and r.get("answer")]

    if sample:
        cases = cases[:sample]

    total = len(cases)
    print(f"  평가 대상: {total}개 케이스  (run_date: {data.get('run_date', '?')[:10]})\n")

    verdicts = {"GROUNDED": 0, "PARTIAL": 0, "HALLUCINATION": 0, "ERROR": 0}
    details  = []

    for i, case in enumerate(cases):
        q   = case["question"]
        ans = case["answer"]
        ctx = case["contexts"]

        print(f"  [{i+1:02d}/{total}] {q[:50]}...", end=" ", flush=True)

        result = await judge_single(q, ans, ctx)
        verdict = result.get("verdict", "ERROR")
        verdicts[verdict] = verdicts.get(verdict, 0) + 1

        citation_check = await verify_citations(ans)
        result["citation_verdict"] = citation_check["verdict"]
        result["citation_missing"] = citation_check["missing"]

        icon = {"GROUNDED": "✅", "PARTIAL": "⚠️", "HALLUCINATION": "❌", "ERROR": "💥"}.get(verdict, "?")
        print(f"{icon} {verdict}")

        details.append({
            "id":       case.get("id", f"#{i+1}"),
            "question": q,
            "verdict":  verdict,
            "reason":   result.get("reason", ""),
            "suspicious_claims": result.get("suspicious_claims", []),
            "answer_preview": ans[:200],
            "citation_verdict": citation_check["verdict"],
            "citation_missing": citation_check["missing"],
        })

        await asyncio.sleep(0.3)

    # 요약 출력
    grounded = verdicts["GROUNDED"]
    partial  = verdicts["PARTIAL"]
    halluc   = verdicts["HALLUCINATION"]
    errors   = verdicts["ERROR"]
    valid    = total - errors

    hall_rate = halluc / max(valid, 1)
    safe_rate = (grounded + partial) / max(valid, 1)

    print(f"\n{'='*65}")
    print(f"  GROUNDED      : {grounded}/{valid}  ({grounded/max(valid,1):.1%})")
    print(f"  PARTIAL       : {partial}/{valid}  ({partial/max(valid,1):.1%})")
    print(f"  HALLUCINATION : {halluc}/{valid}  ({hall_rate:.1%})")
    if errors:
        print(f"  ERROR         : {errors}")
    print(f"\n  할루시네이션율 : {hall_rate:.1%}  |  안전 응답율 : {safe_rate:.1%}")
    print(f"{'='*65}\n")

    # 할루시네이션 케이스 상세
    hall_cases = [d for d in details if d["verdict"] == "HALLUCINATION"]
    if hall_cases:
        print("  ── 할루시네이션 케이스 ──")
        for d in hall_cases:
            print(f"  [{d['id']}] {d['question']}")
            print(f"    이유: {d['reason']}")
            for claim in d.get("suspicious_claims", []):
                print(f"    ❌ {claim}")
        print()

    # Citation Miss 통계
    citation_misses = [r for r in details if r.get("citation_verdict") == "CITATION_MISS"]
    print(f"\n📌 Citation 검증: {len(citation_misses)}/{len(details)} CITATION_MISS")
    for r in citation_misses:
        print(f"  Q: {r.get('question', '')[:50]}")
        for m in r.get("citation_missing", []):
            print(f"    ❌ {m} — DB에 없음")

    output = {
        "generated_at":     datetime.now().isoformat(timespec="seconds"),
        "source_result":    result_path or "latest",
        "total_cases":      total,
        "verdicts":         verdicts,
        "hallucination_rate": round(hall_rate, 4),
        "safe_rate":        round(safe_rate, 4),
        "details":          details,
    }

    out_path = RESULTS_DIR / "hallucination_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료 → {out_path}\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=str, default=None)
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument(
        "--repeat", type=int, default=1,
        help="같은 입력을 N회 판정해 케이스별 흔들림을 본다 (LLM 호출도 N배)",
    )
    args = parser.parse_args()
    if args.repeat > 1:
        asyncio.run(run_repeat(args.repeat, result_path=args.result, sample=args.sample))
    else:
        asyncio.run(run(result_path=args.result, sample=args.sample))
