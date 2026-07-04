import logging
from typing import List, Optional

logger = logging.getLogger("Reranker")

_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            logger.info("✅ Cross-Encoder 모델 로드 완료")
        except Exception as e:
            logger.warning(f"⚠️ Cross-Encoder 로드 실패, 원본 순서 사용: {e}")
    return _model


def rerank(query: str, documents: List[str], top_k: int = 5) -> List[int]:
    if len(documents) <= 1:
        return list(range(len(documents)))

    model = _get_model()
    if model is None:
        return list(range(min(top_k, len(documents))))

    try:
        pairs = [(query, doc) for doc in documents]
        scores = model.predict(pairs)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return ranked[:top_k]
    except Exception as e:
        logger.warning(f"⚠️ Reranking 실패, 원본 순서 사용: {e}")
        return list(range(min(top_k, len(documents))))
