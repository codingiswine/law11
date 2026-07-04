#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_retrieval.py
─────────────────
Qdrant 검색 top-k 파라미터별 성능 비교.

골든 데이터셋의 law_name + article_number 를 정답 레이블로 사용해
top-k = 3 / 5 / 10 일 때 Top-1 accuracy 와 Top-3 recall 을 측정한다.

Top-1 accuracy : rank-1 결과가 정답 조문이면 정확
Top-3 recall   : 상위 3개 중 정답 조문이 하나라도 있으면 정확

실행:
    cd law11_backend
    source .venv/bin/activate
    python -m eval.eval_retrieval
    python -m eval.eval_retrieval --sample 10
"""

import sys
import re
import unicodedata
import asyncio
import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.services.rag_service import get_embedding_async, search_qdrant_async

EVAL_DIR    = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)
GOLDEN_PATH = EVAL_DIR / "golden_dataset.json"

TOP_K_VARIANTS = [3, 5, 10]


def normalize(s: str) -> str:
    return re.sub(r"[\s·]", "", unicodedata.normalize("NFC", s.strip()))


def article_matches(retrieved_articles: List[str], law_name: str, article_number: str) -> bool:
    """retrieved_articles 중 정답 조문이 있는지 확인 (정규화 후 비교)."""
    law_n = normalize(law_name)
    art_n = article_number.strip()
    for art in retrieved_articles:
        art_norm = normalize(art)
        # "법령명제17조" 또는 "제17조" 포함 확인
        if law_n in art_norm and art_n in art_norm:
            return True
    return False


async def evaluate_single(question: str, law_name: str, article_number: str, k: int) -> Dict:
    embedding = await get_embedding_async(question)
    results   = await search_qdrant_async(embedding, limit=k)

    retrieved_articles = []
    scores = []
    for r in results:
        payload = r.get("payload", {})
        r_law   = payload.get("law_name", "")
        r_art   = payload.get("article_number_norm", "")
        label   = f"{r_law} 제{r_art}조" if r_art else r_law
        retrieved_articles.append(label)
        scores.append(r.get("score", 0.0))

    top1_hit = (
        article_matches(retrieved_articles[:1], law_name, article_number)
        if retrieved_articles else False
    )
    top3_hit = (
        article_matches(retrieved_articles[:3], law_name, article_number)
        if retrieved_articles else False
    )
    topk_hit = article_matches(retrieved_articles, law_name, article_number)

    return {
        "top1_hit":  top1_hit,
        "top3_hit":  top3_hit,
        "topk_hit":  topk_hit,
        "top1_score": scores[0] if scores else None,
        "retrieved":  retrieved_articles,
    }


async def run_eval(sample: Optional[int] = None):
    if not GOLDEN_PATH.exists():
        print(f"❌ 골든 데이터셋 없음: {GOLDEN_PATH}")
        return

    with open(GOLDEN_PATH, encoding="utf-8") as f:
        data = json.load(f)

    dataset = data["dataset"]
    # article_number 가 있는 케이스만 평가 (정답 레이블이 있어야 함)
    dataset = [d for d in dataset if d.get("article_number")]
    if sample:
        dataset = dataset[:sample]

    total = len(dataset)
    print(f"\n{'='*65}")
    print(f"  Retrieval 성능 평가 — top-k 비교 ({total}개 케이스)")
    print(f"{'='*65}\n")

    all_results: Dict[int, List[Dict]] = {k: [] for k in TOP_K_VARIANTS}

    for i, item in enumerate(dataset):
        q   = item["question"]
        law = item["law_name"]
        art = item["article_number"]
        print(f"  [{i+1:02d}/{total}] {q[:50]}...")

        for k in TOP_K_VARIANTS:
            try:
                res = await evaluate_single(q, law, art, k)
                all_results[k].append(res)
            except Exception as e:
                print(f"         ❌ top-k={k} 오류: {e}")
                all_results[k].append({
                    "top1_hit": False, "top3_hit": False,
                    "topk_hit": False, "top1_score": None, "retrieved": [],
                })

        await asyncio.sleep(0.3)  # rate limit 방지

    # 메트릭 계산
    summary: Dict[int, Dict] = {}
    for k in TOP_K_VARIANTS:
        results = all_results[k]
        n = len(results)
        if n == 0:
            continue
        top1_acc    = sum(r["top1_hit"] for r in results) / n
        top3_recall = sum(r["top3_hit"] for r in results) / n
        topk_recall = sum(r["topk_hit"] for r in results) / n
        avg_score   = sum(r["top1_score"] for r in results if r["top1_score"]) / max(
            sum(1 for r in results if r["top1_score"]), 1
        )
        summary[k] = {
            "top1_accuracy": round(top1_acc, 4),
            "top3_recall":   round(top3_recall, 4),
            f"top{k}_recall": round(topk_recall, 4),
            "avg_top1_score": round(avg_score, 4),
        }

    # 결과 출력
    print(f"\n{'='*65}")
    print(f"  {'top-k':<8} {'Top-1 Acc':>10} {'Top-3 Recall':>14} {'Avg Score':>11}")
    print(f"  {'-'*45}")
    for k in TOP_K_VARIANTS:
        m = summary.get(k, {})
        bar_len = int(m.get("top1_accuracy", 0) * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"  k={k:<6} {m.get('top1_accuracy', 0):>10.4f} "
              f"{m.get('top3_recall', 0):>14.4f} "
              f"{m.get('avg_top1_score', 0):>11.4f}  {bar}")
    print(f"{'='*65}\n")

    output = {
        "generated_at":  datetime.now().isoformat(timespec="seconds"),
        "total_cases":   total,
        "top_k_variants": TOP_K_VARIANTS,
        "summary":       summary,
        "per_case": {
            str(k): [
                {
                    "question": dataset[i]["question"],
                    "law":      dataset[i]["law_name"],
                    "article":  dataset[i]["article_number"],
                    **all_results[k][i],
                }
                for i in range(total)
            ]
            for k in TOP_K_VARIANTS
            if len(all_results[k]) == total
        }
    }

    out_path = RESULTS_DIR / "retrieval_eval.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료 → {out_path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run_eval(sample=args.sample))
