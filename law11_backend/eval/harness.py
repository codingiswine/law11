#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
harness.py — Law11 Eval Harness v1.0
──────────────────────────────────────────────────────────────
베이스라인 측정 + 회귀 테스트 + smoke test 를 하나의 진입점으로 통합.

실행:
    cd law11_backend
    source .venv/bin/activate

    python -m eval.harness              # 전체 평가 (30개) + 직전 결과와 자동 비교
    python -m eval.harness --smoke      # 빠른 확인 (5개)
    python -m eval.harness --compare    # 새 실행 없이 직전 두 결과만 비교
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from eval.retriever import retrieve_and_generate

# RAGAS
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from datasets import Dataset

# ────────────────────────────────────────────
# 경로
# ────────────────────────────────────────────
EVAL_DIR        = Path(__file__).parent
GOLDEN_PATH     = EVAL_DIR / "golden_dataset.json"
RESULTS_DIR     = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

SMOKE_SIZE      = 5
REGRESSION_THRESHOLD = 0.05   # 5% 이상 하락 → REGRESSION (기본)
# ⚠️ faithfulness는 동일 설정 연속 실행에서도 ±10% 흔들린다 (실측 2026-07-19:
# 같은 시스템 3회 실행이 0.86 → 0.79 → 0.71). LLM-judge의 문장 추출/판정이
# 비결정적이기 때문 — 5% 게이트를 그대로 쓰면 노이즈로 CI가 계속 깨진다.
# 실측 분산보다 넓은 15%만 진짜 회귀로 판정한다.
METRIC_THRESHOLDS = {"faithfulness": 0.15}

# ────────────────────────────────────────────
# RAGAS 설정 (gpt-4o-mini, 비용 절감)
# ────────────────────────────────────────────
_ragas_llm = LangchainLLMWrapper(
    ChatOpenAI(model="gpt-4o-mini", api_key=settings.OPENAI_API_KEY)
)
_ragas_emb = LangchainEmbeddingsWrapper(
    OpenAIEmbeddings(model="text-embedding-3-large", api_key=settings.OPENAI_API_KEY)
)
for _m in [faithfulness, answer_relevancy, context_precision, context_recall]:
    _m.llm = _ragas_llm
answer_relevancy.embeddings = _ragas_emb

METRICS_ORDER = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
METRICS_LABEL = {
    "faithfulness":      "Faithfulness",
    "answer_relevancy":  "Answer Relevancy",
    "context_precision": "Context Precision",
    "context_recall":    "Context Recall",
}

# ────────────────────────────────────────────
# 데이터셋 로드
# ────────────────────────────────────────────
def load_dataset(smoke: bool = False) -> List[Dict]:
    if not GOLDEN_PATH.exists():
        raise FileNotFoundError(
            f"골든 데이터셋 없음: {GOLDEN_PATH}\n"
            "python -m eval.seed_golden_dataset 먼저 실행하세요."
        )
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    dataset = raw["dataset"]

    if smoke:
        # 질문 유형별로 1개씩 선택해 다양성 확보
        seen_types = set()
        selected = []
        for item in dataset:
            qt = item.get("question_type", "unknown")
            if qt not in seen_types:
                seen_types.add(qt)
                selected.append(item)
            if len(selected) >= SMOKE_SIZE:
                break
        # 유형이 부족하면 앞에서 채움
        if len(selected) < SMOKE_SIZE:
            for item in dataset:
                if item not in selected:
                    selected.append(item)
                if len(selected) >= SMOKE_SIZE:
                    break
        return selected

    return dataset


# ────────────────────────────────────────────
# RAG 파이프라인 실행
# ────────────────────────────────────────────
async def run_pipeline(dataset: List[Dict]) -> List[Dict]:
    results = []
    total = len(dataset)
    for i, item in enumerate(dataset):
        q_id = item.get("id", f"#{i+1}")
        print(f"  [{i+1:02d}/{total}] {q_id} — {item['question'][:48]}...")
        try:
            out = await retrieve_and_generate(item["question"])
            results.append({
                "id":               q_id,
                "question_type":    item.get("question_type", "unknown"),
                "law_name":         item.get("law_name", ""),
                "article_number":   item.get("article_number", ""),
                "question":         out["question"],
                "answer":           out["answer"],
                "contexts":         out["contexts"],
                "ground_truth":     item["ground_truth"],
                "retrieved_articles": out["retrieved_articles"],
                "status":           "success",
            })
            print(f"         contexts={len(out['contexts'])}, answer={len(out['answer'])}자")
        except Exception as e:
            print(f"         ❌ ERROR: {e}")
            results.append({
                "id": q_id, "question": item["question"],
                "answer": "", "contexts": [], "ground_truth": item.get("ground_truth", ""),
                "retrieved_articles": [], "status": "error", "error": str(e),
            })
        await asyncio.sleep(0.5)
    return results


# ────────────────────────────────────────────
# RAGAS 평가
# ────────────────────────────────────────────
def compute_ragas(pipeline_results: List[Dict]) -> Dict[str, float]:
    valid = [r for r in pipeline_results if r["status"] == "success" and r["contexts"]]
    if not valid:
        raise ValueError("평가 가능한 결과가 없습니다. retriever / Qdrant 연결을 확인하세요.")

    ds = Dataset.from_dict({
        "question":     [r["question"]     for r in valid],
        "answer":       [r["answer"]       for r in valid],
        "contexts":     [r["contexts"]     for r in valid],
        "ground_truth": [r["ground_truth"] for r in valid],
    })
    score = evaluate(
        dataset=ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )
    return score.to_pandas().mean(numeric_only=True).to_dict()


# ────────────────────────────────────────────
# 결과 저장
# ────────────────────────────────────────────
def save_result(pipeline_results: List[Dict], metrics: Dict, tag: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = RESULTS_DIR / f"baseline_{ts}_{tag}.json"
    payload = {
        "run_date":         datetime.now().isoformat(),
        "harness_version":  "1.0",
        "tag":              tag,
        "dataset_size":     len(pipeline_results),
        "success_count":    sum(1 for r in pipeline_results if r["status"] == "success"),
        "metrics":          metrics,
        "per_case_results": pipeline_results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return path


# ────────────────────────────────────────────
# 직전 결과 로드
# ────────────────────────────────────────────
def load_previous_results(exclude_path: Optional[Path] = None) -> Optional[Dict]:
    """results/ 에서 exclude_path 를 제외한 가장 최신 파일 반환."""
    candidates = sorted(RESULTS_DIR.glob("baseline_*.json"), reverse=True)
    for path in candidates:
        if exclude_path and path == exclude_path:
            continue
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def load_two_latest() -> Tuple[Optional[Dict], Optional[Dict]]:
    """비교 모드용: 최신 2개 로드 (before=두번째, after=첫번째)."""
    candidates = sorted(RESULTS_DIR.glob("baseline_*.json"), reverse=True)
    after, before = None, None
    if len(candidates) >= 1:
        with open(candidates[0], encoding="utf-8") as f:
            after = json.load(f)
    if len(candidates) >= 2:
        with open(candidates[1], encoding="utf-8") as f:
            before = json.load(f)
    return before, after


# ────────────────────────────────────────────
# 비교 + 출력
# ────────────────────────────────────────────
W = 47   # 총 라인 너비 (│ 포함)

def _pad(s: str, width: int) -> str:
    """유니코드 아이콘 포함 문자열을 시각 너비 기준으로 패딩."""
    # ✅ ❌ 〰️ 는 터미널에서 2칸이지만 len()은 1~2 로 다름 → 근사치 보정
    vis_extra = sum(1 for c in s if ord(c) > 0x2FFF)
    pad = width - len(s) - vis_extra
    return s + " " * max(pad, 0)


def _box_line(content: str) -> str:
    inner = W - 2  # │ 두 개 제외
    vis_extra = sum(1 for c in content if ord(c) > 0x2FFF)
    pad = inner - len(content) - vis_extra
    return f"│{content}{' ' * max(pad, 0)}│"


def _delta_str(before: float, after: float, threshold: float = REGRESSION_THRESHOLD) -> Tuple[str, str]:
    """(delta_str, icon) 반환."""
    if before == 0:
        return "  N/A ", "〰️"
    delta = (after - before) / before
    sign  = "+" if delta >= 0 else ""
    s     = f"{sign}{delta*100:.0f}%"
    if delta > threshold:
        icon = "✅"
    elif delta < -threshold:
        icon = "❌"
    else:
        icon = "〰️"
    return s, icon


def print_comparison(
    before_data: Optional[Dict],
    after_data: Dict,
    run_ts: str,
) -> bool:
    """
    비교 테이블 출력. 회귀가 하나라도 있으면 True 반환.
    """
    sep_top    = "┌" + "─" * (W - 2) + "┐"
    sep_mid    = "├" + "─" * (W - 2) + "┤"
    sep_bottom = "└" + "─" * (W - 2) + "┘"

    print(sep_top)
    print(_box_line(f"  Law11 Eval Harness v1.0"))
    print(_box_line(f"  실행: {run_ts}"))

    after_metrics  = after_data.get("metrics", {})
    after_tag      = after_data.get("tag", "?")
    after_n        = after_data.get("dataset_size", "?")

    if before_data:
        before_metrics = before_data.get("metrics", {})
        before_tag     = before_data.get("tag", "?")
        before_run     = before_data.get("run_date", "")[:16]
        print(_box_line(f"  Before: {before_run} ({before_tag}, {before_data.get('dataset_size','?')}개)"))
        print(_box_line(f"  After : 방금 실행 ({after_tag}, {after_n}개)"))
        print(sep_mid)
        print(_box_line(f"  {'Metric':<22} {'Before':>7}  {'After':>7}  {'Δ':>6}  "))
        print(_box_line(f"  {'─'*22}  {'─'*7}  {'─'*7}  {'─'*6}  "))

        has_regression = False
        for key in METRICS_ORDER:
            label  = METRICS_LABEL[key]
            b_val  = before_metrics.get(key)
            a_val  = after_metrics.get(key)
            if b_val is None or a_val is None:
                line = f"  {label:<22} {'N/A':>7}  {'N/A':>7}  {'N/A':>6}  "
                print(_box_line(line))
                continue
            delta_s, icon = _delta_str(b_val, a_val, METRIC_THRESHOLDS.get(key, REGRESSION_THRESHOLD))
            if icon == "❌":
                has_regression = True
            line = f"  {label:<22} {b_val:>7.4f}  {a_val:>7.4f}  {delta_s:>6} {icon}"
            print(_box_line(line))
    else:
        print(_box_line(f"  (직전 결과 없음 — 이번 실행이 첫 베이스라인)"))
        print(_box_line(f"  실행: {after_tag}, {after_n}개 케이스"))
        print(sep_mid)
        print(_box_line(f"  {'Metric':<22} {'Score':>7}  {'Bar':<20}"))
        print(_box_line(f"  {'─'*22}  {'─'*7}  {'─'*20}"))

        has_regression = False
        for key in METRICS_ORDER:
            label = METRICS_LABEL[key]
            val   = after_metrics.get(key)
            if val is None:
                print(_box_line(f"  {label:<22} {'N/A':>7}"))
                continue
            filled = int(val * 16)
            bar    = "█" * filled + "░" * (16 - filled)
            print(_box_line(f"  {label:<22} {val:>7.4f}  {bar}"))

    print(sep_bottom)

    # 종합 판정
    if before_data:
        if has_regression:
            print("\n  ❌ REGRESSION 감지 — 5% 이상 하락한 메트릭이 있습니다.")
        else:
            print("\n  ✅ 회귀 없음 — 모든 메트릭이 안정적입니다.")
    print()
    return has_regression if before_data else False


# ────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────
async def main(smoke: bool = False, compare_only: bool = False):
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── compare-only 모드 ──────────────────────
    if compare_only:
        print("\n  [compare 모드] 저장된 결과 두 개를 비교합니다.\n")
        before, after = load_two_latest()
        if after is None:
            print("  ❌ results/ 에 결과 파일이 없습니다. 먼저 harness 를 실행하세요.")
            return
        if before is None:
            print("  ⚠️  결과가 1개뿐입니다. before 없이 after만 표시합니다.")
        print_comparison(before, after, run_ts)
        return

    # ── 평가 실행 ──────────────────────────────
    tag = "smoke" if smoke else "full"
    print(f"\n{'─'*49}")
    print(f"  Law11 Eval Harness v1.0  [{tag.upper()}]  {run_ts}")
    print(f"{'─'*49}\n")

    dataset = load_dataset(smoke=smoke)
    print(f"  골든 데이터셋: {len(dataset)}개 케이스\n")

    # Step 1: RAG 파이프라인
    print("[Step 1] RAG 파이프라인 실행 중...")
    pipeline_results = await run_pipeline(dataset)
    success_n = sum(1 for r in pipeline_results if r["status"] == "success")
    print(f"\n  완료: {success_n}/{len(dataset)}개 성공\n")

    # Step 2: RAGAS
    print("[Step 2] RAGAS 메트릭 계산 중... (약 2-3분 소요)")
    metrics = compute_ragas(pipeline_results)
    print("  완료\n")

    # Step 3: 저장
    print("[Step 3] 결과 저장 중...")
    saved_path = save_result(pipeline_results, metrics, tag)
    print(f"  → {saved_path}\n")

    # Step 4: 직전 결과와 비교
    print("[Step 4] 직전 결과와 비교...\n")
    before_data = load_previous_results(exclude_path=saved_path)
    after_data  = {"metrics": metrics, "tag": tag,
                   "dataset_size": len(pipeline_results),
                   "run_date": run_ts}

    has_regression = print_comparison(before_data, after_data, run_ts)

    # smoke 모드 안내
    if smoke:
        print("  ⚠️  smoke 모드 (5개). 전체 평가는 python -m eval.harness 실행.")
        print()

    # 회귀 시 exit code 1 (CI 연동용)
    if has_regression:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Law11 Eval Harness v1.0")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=f"골든 데이터셋에서 {SMOKE_SIZE}개만 빠르게 실행",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="새 실행 없이 results/ 의 직전 두 파일만 비교",
    )
    args = parser.parse_args()
    asyncio.run(main(smoke=args.smoke, compare_only=args.compare))
