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
"""

import re
import sys
import asyncio
import argparse
import json
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

[출력 형식 - JSON 그대로]
{
  "verdict": "GROUNDED" | "PARTIAL" | "HALLUCINATION",
  "reason": "한 문장 이유",
  "suspicious_claims": ["조문 근거 없는 주장1", "주장2"]  // PARTIAL/HALLUCINATION 시만
}"""


async def judge_single(question: str, answer: str, contexts: List[str]) -> Dict[str, Any]:
    ctx_block = "\n\n".join(f"[조문 {i+1}]\n{c}" for i, c in enumerate(contexts[:5]))
    user_msg = f"""[사용자 질문]
{question}

[검색된 법령 조문]
{ctx_block}

[AI 답변]
{answer}

위 조문만을 근거로 답변이 올바른지 판정해. JSON만 출력해."""

    try:
        resp = await settings.openai_client.chat.completions.create(
            model="gpt-4o-mini",
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=str, default=None)
    parser.add_argument("--sample", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(result_path=args.result, sample=args.sample))
