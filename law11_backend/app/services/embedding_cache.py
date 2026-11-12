import asyncio
import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

from app.config import settings

logger = logging.getLogger("EmbeddingCache")

CACHE_DIR = Path("/app/.cache") if Path("/app").exists() else Path(".cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
EMBEDDING_CACHE_DB = CACHE_DIR / "embedding_cache.db"


def _init_cache():
    with sqlite3.connect(EMBEDDING_CACHE_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                query_hash TEXT PRIMARY KEY,
                query_text TEXT,
                embedding TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


_init_cache()


def _get_cached_embedding(query: str) -> Optional[List[float]]:
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    with sqlite3.connect(EMBEDDING_CACHE_DB) as conn:
        row = conn.execute(
            "SELECT embedding FROM embeddings WHERE query_hash = ?", (query_hash,)
        ).fetchone()
    if row:
        logger.info(f"✅ 임베딩 캐시 히트: {query[:30]}")
        return json.loads(row[0])
    return None


def _save_embedding(query: str, embedding: List[float]) -> None:
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    with sqlite3.connect(EMBEDDING_CACHE_DB) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (query_hash, query_text, embedding) VALUES (?, ?, ?)",
            (query_hash, query, json.dumps(embedding)),
        )
    logger.info(f"💾 임베딩 캐시 저장: {query[:30]}")


async def get_embedding_async(query: str) -> List[float]:
    # sqlite3는 동기 I/O다 — 이벤트 루프에서 직접 부르면 그 시간 동안 다른 요청의 SSE 스트림이
    # 전부 멈춘다 (#87). 업데이터가 이미 쓰는 asyncio.to_thread로 루프 밖에서 돌린다.
    cached = await asyncio.to_thread(_get_cached_embedding, query)
    if cached is not None:
        return cached

    response = await settings.openai_client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=query,
    )
    embedding = response.data[0].embedding
    await asyncio.to_thread(_save_embedding, query, embedding)
    return embedding
