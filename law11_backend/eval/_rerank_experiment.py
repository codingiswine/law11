#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""리랭커 비교 실험: A) 순수 벡터 B) 영어 CE C) 다국어 CE — 교정된 골든셋 30케이스."""
import sys, json, asyncio, re, unicodedata
from pathlib import Path

BACKEND_ROOT = Path("/app")
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.rag_service import get_embedding_async, search_qdrant_async


def normalize(s):
    return re.sub(r"[\s·]", "", unicodedata.normalize("NFC", s.strip()))


def strict_match(labels, law_name, art_num):
    law_n = normalize(law_name)
    needle = f"제{art_num.strip()}조"
    return any(law_n in normalize(a) and needle in normalize(a) for a in labels)


def load_ce(name):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(name)


async def main():
    gold = json.load(open(BACKEND_ROOT / "eval/golden_dataset.json"))["dataset"]
    ce_en = load_ce("cross-encoder/ms-marco-MiniLM-L-6-v2")
    ce_ml = load_ce("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")

    stats = {p: {"top1": 0, "top3": 0} for p in ["A_vector", "B_en_ce", "C_ml_ce"]}
    for i, g in enumerate(gold):
        q, law, art = g["question"], g["law_name"], g["article_number_norm"]
        emb = await get_embedding_async(q)
        results = await search_qdrant_async(emb, limit=10)
        labels, docs = [], []
        for r in results:
            p = r.get("payload", {})
            labels.append(f"{p.get('law_name','')} 제{p.get('article_number_norm','')}조")
            docs.append(p.get("text", ""))

        rankings = {"A_vector": list(range(len(docs)))}
        for key, ce in [("B_en_ce", ce_en), ("C_ml_ce", ce_ml)]:
            scores = ce.predict([(q, d) for d in docs])
            rankings[key] = sorted(range(len(scores)), key=lambda j: scores[j], reverse=True)

        line = [f"[{i+1:02d}] {q[:24]:<26}"]
        for key, order in rankings.items():
            ordered = [labels[j] for j in order]
            t1 = strict_match(ordered[:1], law, art)
            t3 = strict_match(ordered[:3], law, art)
            stats[key]["top1"] += t1
            stats[key]["top3"] += t3
            line.append(f"{key[0]}:{'T1' if t1 else ('T3' if t3 else '--')}")
        print("  ".join(line), flush=True)

    n = len(gold)
    print("\n  파이프라인            Top-1     Top-3")
    for key, s in stats.items():
        print(f"  {key:<20} {s['top1']/n:>6.1%}   {s['top3']/n:>6.1%}")


if __name__ == "__main__":
    asyncio.run(main())
