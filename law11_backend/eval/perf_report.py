#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
perf_report.py
──────────────
QA 로그 + run_qa_test 결과에서 성능 지표를 계산한다.

측정 항목:
  - Fallback 비율 (web fallback 사용 비율)
  - 에러율 (selected_source == 'none')
  - Confidence score 분포 (p25/p50/p75/p95)
  - Source 분포 (pg / qdrant / web / none)
  - Tool 분포
  - 응답 시간 p95 (run_qa_test failures 파일에서 추출, 없으면 N/A)

실행:
    cd law11_backend
    source .venv/bin/activate
    python -m eval.perf_report
"""

import json
import statistics
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

EVAL_DIR     = Path(__file__).parent
LOG_DIR      = EVAL_DIR / "logs"
FAILURES_DIR = EVAL_DIR / "failures"
RESULTS_DIR  = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def percentile(data: List[float], p: float) -> Optional[float]:
    if not data:
        return None
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def load_qa_logs() -> List[Dict]:
    entries: List[Dict] = []
    if not LOG_DIR.exists():
        return entries
    for log_file in sorted(LOG_DIR.glob("qa_*.jsonl")):
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return entries


def analyze_logs(entries: List[Dict]) -> Dict[str, Any]:
    if not entries:
        return {}

    n = len(entries)

    # Fallback & error
    fallback_count = sum(1 for e in entries if e.get("fallback_used", False))
    no_article_count = sum(1 for e in entries if not e.get("selected_articles"))
    error_count = sum(1 for e in entries if e.get("selected_source") == "none")

    # Source 분포
    source_dist: Dict[str, int] = {}
    for e in entries:
        src = e.get("selected_source") or "none"
        source_dist[src] = source_dist.get(src, 0) + 1

    # Query type 분포
    qtype_dist: Dict[str, int] = {}
    for e in entries:
        qt = e.get("query_type") or "unknown"
        qtype_dist[qt] = qtype_dist.get(qt, 0) + 1

    # Tool 분포
    tool_dist: Dict[str, int] = {}
    for e in entries:
        t = e.get("tool") or "unknown"
        tool_dist[t] = tool_dist.get(t, 0) + 1

    # Confidence score 분포
    scores = [e["confidence_score"] for e in entries
              if e.get("confidence_score") is not None]
    score_stats: Dict[str, Any] = {}
    if scores:
        score_stats = {
            "count":  len(scores),
            "mean":   round(statistics.mean(scores), 4),
            "p25":    round(percentile(scores, 25), 4),
            "p50":    round(percentile(scores, 50), 4),
            "p75":    round(percentile(scores, 75), 4),
            "p95":    round(percentile(scores, 95), 4),
            "min":    round(min(scores), 4),
            "max":    round(max(scores), 4),
        }

    return {
        "total_requests":    n,
        "fallback_count":    fallback_count,
        "fallback_rate":     round(fallback_count / n, 4),
        "no_article_count":  no_article_count,
        "no_article_rate":   round(no_article_count / n, 4),
        "error_count":       error_count,
        "error_rate":        round(error_count / n, 4),
        "source_dist":       source_dist,
        "query_type_dist":   qtype_dist,
        "tool_dist":         tool_dist,
        "confidence_scores": score_stats,
    }


def analyze_response_times() -> Dict[str, Any]:
    """run_qa_test failures 파일에서 응답 시간 추출 (미래 확장용 — 현재 저장 안 됨)."""
    return {"note": "run_qa_test.py가 응답 시간을 failures 파일에 저장하지 않으므로 N/A. "
                    "실시간 측정은 Prometheus metrics /api/metrics 를 확인하세요."}


def print_report(report: Dict[str, Any]):
    log = report.get("log_analysis", {})
    if not log:
        print("  ⚠️  QA 로그가 없습니다. API 서버를 통해 쿼리를 보내면 로그가 쌓입니다.")
        return

    n = log.get("total_requests", 0)
    print(f"  총 요청 수    : {n}")
    print(f"  Fallback 비율 : {log['fallback_rate']:.1%}  ({log['fallback_count']}건)")
    print(f"  조문 미발견   : {log['no_article_rate']:.1%}  ({log['no_article_count']}건)")
    print(f"  에러율        : {log['error_rate']:.1%}  ({log['error_count']}건)")

    print("\n  ── Source 분포 ──")
    for src, cnt in sorted(log.get("source_dist", {}).items(), key=lambda x: -x[1]):
        pct = cnt / max(n, 1)
        bar = "█" * int(pct * 30)
        print(f"    {src:<12} {cnt:>5}건  {pct:>6.1%}  {bar}")

    cs = log.get("confidence_scores", {})
    if cs:
        print(f"\n  ── Confidence Score 분포 ({cs.get('count')}건 중 None 제외) ──")
        print(f"    평균={cs.get('mean'):.3f}  "
              f"p25={cs.get('p25'):.3f}  p50={cs.get('p50'):.3f}  "
              f"p75={cs.get('p75'):.3f}  p95={cs.get('p95'):.3f}")


def main():
    print(f"\n{'='*55}")
    print(f"  Law11 성능 리포트")
    print(f"{'='*55}\n")

    entries = load_qa_logs()
    log_analysis = analyze_logs(entries)
    resp_time    = analyze_response_times()

    report = {
        "generated_at":  datetime.now().isoformat(timespec="seconds"),
        "log_files":     len(list(LOG_DIR.glob("qa_*.jsonl"))) if LOG_DIR.exists() else 0,
        "log_analysis":  log_analysis,
        "response_time": resp_time,
        "note": "응답 시간 p95는 Prometheus /api/metrics 에서 law11_response_time_seconds 확인",
    }

    print_report(report)

    out_path = RESULTS_DIR / "perf_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  저장 완료 → {out_path}\n")


if __name__ == "__main__":
    main()
