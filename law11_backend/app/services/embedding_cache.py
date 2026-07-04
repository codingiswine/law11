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
    cached = _get_cached_embedding(query)
    if cached is not None:
        return cached

    response = await settings.openai_client.embeddings.create(
        model="text-embedding-3-large",
        input=query,
    )
    embedding = response.data[0].embedding
    _save_embedding(query, embedding)
    return embedding
