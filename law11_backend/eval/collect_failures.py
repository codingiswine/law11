#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_failures.py
────────────────────
QA JSONL 로그에서 실패 케이스를 추출해 failures/failures.json 으로 저장한다.

실패 조건 (OR):
  - fallback_used == true
  - confidence_score < 0.7  (None은 실패로 간주)
  - selected_articles == []

실행:
    cd law11_backend
    source .venv/bin/activate
    python -m eval.collect_failures
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

LOG_DIR      = Path(__file__).parent / "logs"
FAILURES_DIR = Path(__file__).parent / "failures"
FAILURES_DIR.mkdir(exist_ok=True)

CONF_THRESHOLD = 0.7


def is_failure(entry: Dict[str, Any]) -> bool:
    if entry.get("fallback_used", False):
        return True
    score = entry.get("confidence_score")
    if score is None or score < CONF_THRESHOLD:
        return True
    if not entry.get("selected_articles"):
        return True
    return False


def classify_failure_reason(entry: Dict[str, Any]) -> str:
    reasons = []
    if entry.get("fallback_used", False):
        reasons.append("fallback_used")
    score = entry.get("confidence_score")
    if score is None:
        reasons.append("confidence_null")
    elif score < CONF_THRESHOLD:
        reasons.append(f"low_confidence({score:.3f})")
    if not entry.get("selected_articles"):
        reasons.append("no_articles")
    return " | ".join(reasons) if reasons else "unknown"


def collect() -> Dict[str, Any]:
    if not LOG_DIR.exists() or not list(LOG_DIR.glob("qa_*.jsonl")):
        print("⚠️  eval/logs/ 에 QA 로그가 없습니다.")
        print("   API 서버를 실행하고 쿼리를 보내면 로그가 쌓입니다.")
        return {"total_entries": 0, "total_failures": 0, "failures": []}

    all_entries: List[Dict] = []
    for log_file in sorted(LOG_DIR.glob("qa_*.jsonl")):
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        all_entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    failures = []
    for entry in all_entries:
        if is_failure(entry):
            failures.append({
                **entry,
                "_failure_reason": classify_failure_reason(entry),
            })

    # 소스별 실패 분포
    source_dist: Dict[str, int] = {}
    query_type_dist: Dict[str, int] = {}
    for f in failures:
        src = f.get("selected_source", "unknown")
        qt  = f.get("query_type", "unknown")
        source_dist[src] = source_dist.get(src, 0) + 1
        query_type_dist[qt] = query_type_dist.get(qt, 0) + 1

    result = {
        "generated_at":    datetime.now().isoformat(timespec="seconds"),
        "total_entries":   len(all_entries),
        "total_failures":  len(failures),
        "failure_rate":    round(len(failures) / max(len(all_entries), 1), 4),
        "source_dist":     source_dist,
        "query_type_dist": query_type_dist,
        "criteria": {
            "fallback_used":         True,
            "confidence_score_lt":   CONF_THRESHOLD,
            "selected_articles_empty": True,
        },
        "failures": failures,
    }
    return result


def main():
    print("=" * 55)
    print("  Law11 — 실패 케이스 수집기")
    print("=" * 55)

    data = collect()

    out_path = FAILURES_DIR / "failures.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n  전체 로그:  {data['total_entries']}건")
    print(f"  실패 케이스: {data['total_failures']}건  "
          f"(실패율 {data['failure_rate']:.1%})")
    if data["source_dist"]:
        print("\n  소스별 분포:")
        for src, cnt in sorted(data["source_dist"].items(), key=lambda x: -x[1]):
            print(f"    {src:<12} {cnt}건")
    print(f"\n  저장 완료 → {out_path}\n")


if __name__ == "__main__":
    main()
