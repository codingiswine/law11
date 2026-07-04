import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.question_router import (
    _check_vector_relevance,
    _vector_relevance_cache,
    _llm_cache,
    detect_tool,
)


@pytest.mark.asyncio
async def test_check_vector_relevance_high_score():
    """Qdrant score >= 0.45 → 해당 score 반환"""
    mock_hit = MagicMock()
    mock_hit.score = 0.8

    with patch("app.services.question_router.get_embedding_async", new_callable=AsyncMock) as mock_emb, \
         patch("app.services.question_router.settings") as mock_settings:
        mock_emb.return_value = [0.1] * 3072
        mock_settings.qdrant_client.search = AsyncMock(return_value=[mock_hit])
        mock_settings.QDRANT_COLLECTION_NAME = "laws"

        score = await _check_vector_relevance("안전관리자 선임 기준은?")

    assert score == 0.8


@pytest.mark.asyncio
async def test_check_vector_relevance_low_score():
    """Qdrant score < 0.45 → 해당 score 반환"""
    mock_hit = MagicMock()
    mock_hit.score = 0.2

    with patch("app.services.question_router.get_embedding_async", new_callable=AsyncMock) as mock_emb, \
         patch("app.services.question_router.settings") as mock_settings:
        mock_emb.return_value = [0.1] * 3072
        mock_settings.qdrant_client.search = AsyncMock(return_value=[mock_hit])
        mock_settings.QDRANT_COLLECTION_NAME = "laws"

        score = await _check_vector_relevance("오늘 날씨 어때?")

    assert score == 0.2


@pytest.mark.asyncio
async def test_check_vector_relevance_empty_results():
    """Qdrant 결과 없음 → 0.0 반환"""
    with patch("app.services.question_router.get_embedding_async", new_callable=AsyncMock) as mock_emb, \
         patch("app.services.question_router.settings") as mock_settings:
        mock_emb.return_value = [0.1] * 3072
        mock_settings.qdrant_client.search = AsyncMock(return_value=[])
        mock_settings.QDRANT_COLLECTION_NAME = "laws"

        score = await _check_vector_relevance("전혀 관계없는 질문")

    assert score == 0.0


@pytest.mark.asyncio
async def test_check_vector_relevance_error_returns_safe_value():
    """임베딩/Qdrant 에러 → 1.0 반환 (law_rag_tool 유지 방향)"""
    with patch("app.services.question_router.get_embedding_async", new_callable=AsyncMock) as mock_emb:
        mock_emb.side_effect = Exception("OpenAI connection error")

        score = await _check_vector_relevance("에러 발생 케이스")

    assert score == 1.0


@pytest.mark.asyncio
async def test_check_vector_relevance_uses_cache():
    """동일 질문 두 번째 호출 → Qdrant 호출 없이 캐시 반환"""
    _vector_relevance_cache.clear()
    _vector_relevance_cache["캐시 테스트 질문"] = 0.75

    with patch("app.services.question_router.get_embedding_async", new_callable=AsyncMock) as mock_emb:
        score = await _check_vector_relevance("캐시 테스트 질문")

    mock_emb.assert_not_called()
    assert score == 0.75
    _vector_relevance_cache.clear()


@pytest.mark.asyncio
async def test_detect_tool_llm_law_low_relevance_redirects_to_websearch():
    """LLM이 law_rag_tool 선택 + Qdrant score < 0.45 → websearch_tool로 전환"""
    _llm_cache.clear()
    _vector_relevance_cache.clear()

    with patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.question_router._check_vector_relevance", new_callable=AsyncMock) as mock_vec, \
         patch("app.services.question_router._load_session_context", new_callable=AsyncMock, return_value=""):
        mock_llm.return_value = "law_rag_tool"
        mock_vec.return_value = 0.2

        plan = await detect_tool("user1", "피자 맛집 추천해줘")

    assert plan.tool == "websearch_tool"
    mock_vec.assert_called_once()


@pytest.mark.asyncio
async def test_detect_tool_llm_law_high_relevance_keeps_law_rag_tool():
    """LLM이 law_rag_tool 선택 + Qdrant score >= 0.45 → law_rag_tool 유지"""
    _llm_cache.clear()
    _vector_relevance_cache.clear()

    with patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.question_router._check_vector_relevance", new_callable=AsyncMock) as mock_vec, \
         patch("app.services.question_router._load_session_context", new_callable=AsyncMock, return_value=""):
        mock_llm.return_value = "law_rag_tool"
        mock_vec.return_value = 0.7

        plan = await detect_tool("user1", "안전관리자 선임 요건은?")

    assert plan.tool == "law_rag_tool"


@pytest.mark.asyncio
async def test_detect_tool_fast_path_skips_vector_check():
    """fast-path(법령 키워드) → _check_vector_relevance 호출 없음"""
    with patch("app.services.question_router._check_vector_relevance", new_callable=AsyncMock) as mock_vec, \
         patch("app.services.question_router._load_session_context", new_callable=AsyncMock, return_value=""):
        plan = await detect_tool("user1", "산업안전보건법 조문 알려줘")

    mock_vec.assert_not_called()
    assert plan.tool == "law_rag_tool"


@pytest.mark.asyncio
async def test_detect_tool_non_law_tool_skips_vector_check():
    """LLM이 news_tool 선택 → _check_vector_relevance 호출 없음"""
    _llm_cache.clear()

    with patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.question_router._check_vector_relevance", new_callable=AsyncMock) as mock_vec, \
         patch("app.services.question_router._load_session_context", new_callable=AsyncMock, return_value=""):
        mock_llm.return_value = "news_tool"

        plan = await detect_tool("user1", "최근 산업재해 뉴스")

    mock_vec.assert_not_called()
    assert plan.tool == "news_tool"
