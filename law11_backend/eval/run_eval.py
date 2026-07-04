#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_eval.py
─────────────────────────────────────────────────────────────
RAGAS를 사용한 오프라인 RAG 평가 실행기.

골든 데이터셋(golden_dataset.json)을 로드해 각 질문에 대해
RAG 파이프라인을 실행하고 RAGAS 4개 메트릭을 측정한다.

실행:
    cd law11_backend
    source .venv/bin/activate
    python -m eval.run_eval              # 전체 30개
    python -m eval.run_eval --sample 3  # 빠른 테스트 (3개만)
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from eval.retriever import retrieve_and_generate

# RAGAS 및 평가 의존성
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from datasets import Dataset

EVAL_DIR = Path(__file__).parent
GOLDEN_DATASET_PATH = EVAL_DIR / "golden_dataset.json"
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# RAGAS가 사용할 LLM을 gpt-4o-mini로 교체 (비용 절감)
_ragas_llm = LangchainLLMWrapper(
    ChatOpenAI(model="gpt-4o-mini", api_key=settings.OPENAI_API_KEY)
)
_ragas_embeddings = LangchainEmbeddingsWrapper(
    OpenAIEmbeddings(model="text-embedding-3-large", api_key=settings.OPENAI_API_KEY)
)
for _metric in [faithfulness, answer_relevancy, context_precision, context_recall]:
    _metric.llm = _ragas_llm
answer_relevancy.embeddings = _ragas_embeddings


# ─────────────────────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────────────────────
def load_golden_dataset(sample: Optional[int] = None) -> List[Dict]:
    if not GOLDEN_DATASET_PATH.exists():
        raise FileNotFoundError(
            f"{GOLDEN_DATASET_PATH} 파일이 없습니다.\n"
            "먼저 'python -m eval.seed_golden_dataset' 실행 후 "
            "golden_dataset.json을 생성하세요."
        )
    with open(GOLDEN_DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    dataset = data["dataset"]
    if sample:
        dataset = dataset[:sample]
    return dataset


# ─────────────────────────────────────────────────────────────
# RAG 파이프라인 실행
# ─────────────────────────────────────────────────────────────
async def run_pipeline_on_dataset(dataset: List[Dict]) -> List[Dict]:
    results = []
    total = len(dataset)

    for i, item in enumerate(dataset):
        q_id = item.get("id", f"#{i+1}")
        print(f"  [{i+1:02d}/{total}] {q_id} — {item['question'][:50]}...")

        try:
            result = await retrieve_and_generate(item["question"])
            results.append({
                "id": q_id,
                "question_type": item.get("question_type", "unknown"),
                "law_name": item.get("law_name", ""),
                "article_number": item.get("article_number", ""),
                "question": result["question"],
                "answer": result["answer"],
                "contexts": result["contexts"],
                "ground_truth": item["ground_truth"],
                "retrieved_articles": result["retrieved_articles"],
                "status": "success",
            })
            ctx_count = len(result["contexts"])
            print(f"         contexts={ctx_count}, answer={len(result['answer'])}자")
        except Exception as e:
            print(f"         ❌ ERROR: {e}")
            results.append({
                "id": q_id,
                "question": item["question"],
                "answer": "",
                "contexts": [],
                "ground_truth": item.get("ground_truth", ""),
                "retrieved_articles": [],
                "status": "error",
                "error": str(e),
            })

        # API Rate limit 방지
        await asyncio.sleep(0.5)

    return results


# ─────────────────────────────────────────────────────────────
# RAGAS 평가
# ─────────────────────────────────────────────────────────────
def build_ragas_dataset(results: List[Dict]) -> Dataset:
    successful = [r for r in results if r["status"] == "success" and r["contexts"]]
    if not successful:
        raise ValueError("평가 가능한 결과가 없습니다. retriever 출력을 확인하세요.")
    return Dataset.from_dict({
        "question":     [r["question"]     for r in successful],
        "answer":       [r["answer"]       for r in successful],
        "contexts":     [r["contexts"]     for r in successful],  # List[List[str]]
        "ground_truth": [r["ground_truth"] for r in successful],
    })


# ─────────────────────────────────────────────────────────────
# 결과 출력
# ─────────────────────────────────────────────────────────────
def print_metrics_table(metrics: Dict, pipeline_results: List[Dict]):
    success = [r for r in pipeline_results if r["status"] == "success"]

    print("\n" + "=" * 65)
    print("  Law11 RAG 평가 결과 — Phase 1 Baseline")
    print("=" * 65)
    print(f"  데이터셋: {len(pipeline_results)}개 | 성공: {len(success)}개 | "
          f"실패: {len(pipeline_results) - len(success)}개")
    print("-" * 65)
    print(f"  {'Metric':<28} {'Score':>8}  {'Bar':}")
    print("-" * 65)

    display = {
        "faithfulness":      "Faithfulness (충실도)",
        "answer_relevancy":  "Answer Relevancy (관련성)",
        "context_precision": "Context Precision (정밀도)",
        "context_recall":    "Context Recall (재현율)",
    }

    for key, name in display.items():
        score = metrics.get(key)
        if isinstance(score, float):
            filled = int(score * 20)
            bar = "█" * filled + "░" * (20 - filled)
            print(f"  {name:<28} {score:>6.4f}  {bar}")
        else:
            print(f"  {name:<28} {'N/A':>8}")

    print("=" * 65)

    # 질문 유형별 분석
    type_groups: Dict[str, List] = {}
    for r in success:
        qt = r.get("question_type", "unknown")
        type_groups.setdefault(qt, []).append(r)

    if len(type_groups) > 1:
        print("\n  질문 유형별 검색 성공률:")
        for qt, items in sorted(type_groups.items()):
            has_ctx = sum(1 for r in items if r["contexts"])
            print(f"    {qt:<20} {has_ctx}/{len(items)} 조문 검색됨")

    print()


# ─────────────────────────────────────────────────────────────
# 저장
# ─────────────────────────────────────────────────────────────
def save_results(pipeline_results: List[Dict], metrics: Dict, sample: Optional[int]):
    today = datetime.now().strftime("%Y%m%d_%H%M")
    tag = f"sample{sample}" if sample else "full"
    output_path = RESULTS_DIR / f"baseline_{today}_{tag}.json"

    output = {
        "run_date":        datetime.now().isoformat(),
        "pipeline":        "phase1_baseline",
        "dataset_path":    str(GOLDEN_DATASET_PATH),
        "dataset_size":    len(pipeline_results),
        "success_count":   sum(1 for r in pipeline_results if r["status"] == "success"),
        "metrics":         metrics,
        "per_case_results": pipeline_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"  결과 저장: {output_path}")
    return output_path


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────
async def main(sample: Optional[int] = None):
    print("=" * 65)
    print("  Law11 RAG 평가 파이프라인 — Phase 1")
    print("=" * 65)
    if sample:
        print(f"  ⚠️  샘플 모드: 상위 {sample}개만 실행\n")

    # 1. 골든 데이터셋 로드
    dataset = load_golden_dataset(sample)
    print(f"  골든 데이터셋: {GOLDEN_DATASET_PATH.name} ({len(dataset)}개)\n")

    # 2. RAG 파이프라인 실행
    print("[Step 1] RAG 파이프라인 실행 중...")
    pipeline_results = await run_pipeline_on_dataset(dataset)
    success_count = sum(1 for r in pipeline_results if r["status"] == "success")
    print(f"\n  완료: {success_count}/{len(dataset)}개 성공\n")

    # 3. RAGAS 평가
    print("[Step 2] RAGAS 메트릭 계산 중... (약 2-3분 소요)")
    ragas_dataset = build_ragas_dataset(pipeline_results)
    score_result = evaluate(
        dataset=ragas_dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )
    metrics = score_result.to_pandas().mean(numeric_only=True).to_dict()

    # 4. 결과 출력
    print_metrics_table(metrics, pipeline_results)

    # 5. 저장
    print("[Step 3] 결과 저장 중...")
    save_results(pipeline_results, metrics, sample)

    print("\nPhase 1 평가 완료.")
    print("다음 단계: Phase 2에서 Qdrant 필터 버그를 수정하고 재평가해 개선 수치를 확인합니다.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Law11 RAG 평가 실행기")
    parser.add_argument(
        "--sample", type=int, default=None,
        help="빠른 테스트를 위해 상위 N개만 실행 (예: --sample 3)"
    )
    args = parser.parse_args()
    asyncio.run(main(sample=args.sample))
