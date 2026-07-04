#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
improvement_loop.py
────────────────────
실패 케이스를 자동으로 재테스트하고 개선 전/후를 비교한다.

워크플로우:
  1. failures/failures.json 또는 failures/*.json 에서 실패 쿼리 로드
  2. 각 쿼리를 /api/ask 에 다시 전송
  3. 응답을 평가해서 개선 여부 판정
  4. 개선 전 결과(baseline)와 비교해 delta 출력

실행:
    cd law11_backend
    source .venv/bin/activate
    python -m eval.improvement_loop                           # failures.json 사용
    python -m eval.improvement_loop --baseline failures.json  # 특정 파일 지정
    python -m eval.improvement_loop --sample 10               # 빠른 테스트
"""

import sys
import argparse
import json
import time
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

EVAL_DIR     = Path(__file__).parent
FAILURES_DIR = EVAL_DIR / "failures"
RESULTS_DIR  = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

API_URL = "http://localhost:8000/api/ask"


# ──────────────────────────────────────────────
# SSE 수집
# ──────────────────────────────────────────────
def call_api(query: str, timeout: int = 60) -> Dict[str, Any]:
    text_parts: List[str] = []
    source    = "unknown"
    fallback  = False
    articles: List[str] = []
    error     = None
    t0        = time.time()

    try:
        with requests.post(
            API_URL,
            json={"question": query},
            stream=True,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                try:
                    data    = json.loads(line)
                    event   = data.get("event") or data.get("type", "")
                    payload = data.get("payload", "")

                    if event == "text":
                        text_parts.append(str(payload))
                    elif event == "source":
                        if isinstance(payload, dict):
                            if payload.get("law_url"):
                                source = "pg"
                                articles.append(payload["law_url"])
                            elif payload.get("retrieved_laws"):
                                source = "qdrant"
                                articles = payload["retrieved_laws"]
                        elif "web" in str(payload).lower():
                            source = "web"
                            fallback = True
                    elif event == "status":
                        if "Web" in str(payload) and "fallback" in str(payload).lower():
                            fallback = True
                except (json.JSONDecodeError, TypeError):
                    pass

    except requests.exceptions.RequestException as e:
        error = str(e)

    elapsed = time.time() - t0
    full_text = "".join(text_parts)

    # 소스 추론
    if source == "unknown" and full_text:
        source = "pg" if articles else "unknown"

    return {
        "text":     full_text,
        "source":   source,
        "fallback": fallback,
        "articles": articles,
        "elapsed":  round(elapsed, 2),
        "error":    error,
    }


# ──────────────────────────────────────────────
# 개선 여부 판정
# ──────────────────────────────────────────────
def is_improved(original: Dict, new_response: Dict) -> bool:
    orig_reasons = original.get("_failure_reason", "")

    if new_response.get("error"):
        return False

    text = new_response.get("text", "")
    if len(text) < 50:
        return False

    # fallback_used 였던 케이스: 이번엔 fallback 안 썼으면 개선
    if "fallback_used" in orig_reasons:
        if not new_response.get("fallback"):
            return True

    # selected_articles 없었던 케이스: 이번엔 articles 있으면 개선
    if "no_articles" in orig_reasons:
        if new_response.get("articles"):
            return True

    # 텍스트가 충분히 길고 오류 없으면 개선으로 판정
    if len(text) > 200 and not new_response.get("fallback"):
        return True

    return False


# ──────────────────────────────────────────────
# 메인 루프
# ──────────────────────────────────────────────
def run(baseline_path: Optional[str] = None, sample: Optional[int] = None):
    # 실패 케이스 로드
    if baseline_path:
        path = Path(baseline_path)
    else:
        path = FAILURES_DIR / "failures.json"

    if not path.exists():
        # failures 디렉토리에서 최신 파일 탐색
        jsons = sorted(FAILURES_DIR.glob("*.json"), reverse=True)
        if not jsons:
            print("❌ 실패 케이스 파일이 없습니다.")
            print("   먼저 python -m eval.collect_failures 또는 python eval/run_qa_test.py 실행하세요.")
            return
        path = jsons[0]

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # failures.json (collect_failures) vs run_qa_test failures 형식 모두 지원
    if "failures" in data:
        failures = data["failures"]
        failure_type = "log"
    elif isinstance(data, dict) and "failures" in data:
        failures = data["failures"]
        failure_type = "qa_test"
    else:
        failures = [data] if isinstance(data, dict) else data
        failure_type = "raw"

    if sample:
        failures = failures[:sample]

    total = len(failures)
    if total == 0:
        print("✅ 실패 케이스가 없습니다. 개선 불필요.")
        return

    print(f"\n{'='*65}")
    print(f"  개선 루프 — {total}개 실패 케이스 재테스트")
    print(f"  소스: {path}")
    print(f"{'='*65}\n")

    improved_count = 0
    still_failing  = 0
    results        = []

    for i, failure in enumerate(failures):
        # 쿼리 추출 (형식에 따라)
        query = (
            failure.get("query") or
            failure.get("question") or
            failure.get("q", "")
        )
        if not query:
            continue

        orig_reason = failure.get("_failure_reason", failure.get("failure_class", "?"))
        print(f"  [{i+1:02d}/{total}] {query[:50]}...", end=" ", flush=True)

        response = call_api(query)

        improved = is_improved(failure, response)
        if improved:
            improved_count += 1
        else:
            still_failing += 1

        icon = "✅ 개선" if improved else "❌ 미개선"
        print(f"{icon}  ({response['elapsed']:.1f}s)  fallback={response['fallback']}")

        results.append({
            "query":         query,
            "orig_reason":   orig_reason,
            "improved":      improved,
            "new_source":    response["source"],
            "new_fallback":  response["fallback"],
            "new_articles":  response["articles"],
            "elapsed":       response["elapsed"],
            "answer_len":    len(response["text"]),
            "error":         response["error"],
        })

    improvement_rate = improved_count / max(total, 1)

    print(f"\n{'='*65}")
    print(f"  개선됨     : {improved_count}/{total}  ({improvement_rate:.1%})")
    print(f"  아직 실패  : {still_failing}/{total}")
    print(f"{'='*65}\n")

    # 아직 실패 중인 케이스 상세
    still_fail_cases = [r for r in results if not r["improved"]]
    if still_fail_cases:
        print("  ── 아직 실패 케이스 ──")
        for r in still_fail_cases:
            print(f"    {r['query'][:55]}")
            print(f"      원인={r['orig_reason']}  fallback={r['new_fallback']}  "
                  f"articles={r['new_articles']}")
        print()

    output = {
        "generated_at":    datetime.now().isoformat(timespec="seconds"),
        "baseline_path":   str(path),
        "total_retested":  total,
        "improved":        improved_count,
        "still_failing":   still_failing,
        "improvement_rate": round(improvement_rate, 4),
        "results":         results,
    }

    today = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = RESULTS_DIR / f"improvement_loop_{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료 → {out_path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=str, default=None, help="실패 케이스 JSON 파일 경로")
    parser.add_argument("--sample",   type=int, default=None, help="처음 N개만 테스트")
    args = parser.parse_args()
    run(baseline_path=args.baseline, sample=args.sample)
