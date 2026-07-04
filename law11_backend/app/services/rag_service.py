import logging
import time
from typing import Dict, List, Any
from app.config import settings
from app.services.embedding_cache import get_embedding_async  # noqa: F401  re-export

logger = logging.getLogger("RAGService")

qdrant_client = settings.qdrant_client


async def search_qdrant_async(vector: List[float], limit: int = 5) -> List[Dict[str, Any]]:
    start_time = time.time()
    results = await qdrant_client.search(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        query_vector=vector,
        limit=limit,
        with_payload=True
    )
    logger.info(f"⏱️ Qdrant 검색 시간: {time.time() - start_time:.2f}s")
    return [{"id": hit.id, "score": hit.score, "payload": hit.payload} for hit in results]
