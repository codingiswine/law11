import pytest
from unittest.mock import AsyncMock, patch

from app.services.question_router import (
    _llm_cache,
    detect_tool,
)


@pytest.mark.asyncio
async def test_detect_tool_llm_law_goes_straight_to_law_rag_tool():
    """LLM이 law_rag_tool 선택 → 관련도 게이트 없이 그대로 law_rag_tool
    (회귀 테스트: Qdrant top-1 score < 0.45면 websearch_tool로 강등하던 게이트가
    진짜 법령 질문 "산재 은폐하면 어떻게 되나요?"(0.41)를 강등시키던 버그 —
    DB 커버리지 판단은 law_rag_tool 내부 PG→Qdrant→web fallback 체인에 위임)"""
    _llm_cache.clear()

    with patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.question_router._load_session_context", new_callable=AsyncMock, return_value=""):
        mock_llm.return_value = "law_rag_tool"

        plan = await detect_tool("user1", "산재 은폐하면 어떻게 되나요?")

    assert plan.tool == "law_rag_tool"


@pytest.mark.asyncio
async def test_detect_tool_fast_path_law_keyword():
    """fast-path(법령 키워드) → LLM 분류 없이 law_rag_tool"""
    with patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.question_router._load_session_context", new_callable=AsyncMock, return_value=""):
        plan = await detect_tool("user1", "산업안전보건법 조문 알려줘")

    mock_llm.assert_not_called()
    assert plan.tool == "law_rag_tool"


@pytest.mark.asyncio
async def test_detect_tool_ignores_law_keywords_from_session_history():
    """이전 턴 답변에 법령 키워드가 있어도, 현재 질문 자체의 뉴스 키워드로 라우팅되어야 함
    (회귀 테스트: '계단 관련 사고 뉴스 찾아봐'가 이전 턴의 '기준/법적 근거' 문구 때문에
    LAW_RAG_TOOL로 잘못 분류되던 버그)"""
    law_heavy_history = (
        "사용자: 비계 설치 안전 기준 알려줘\n"
        "Law11: 🔹 법적 근거\n[산업안전보건법] 제39조 제1항: 사업주는 필요한 조치를 취하여야 한다."
    )
    with patch("app.services.question_router._load_session_context", new_callable=AsyncMock, return_value=law_heavy_history):
        plan = await detect_tool("user1", "계단 관련 사고 뉴스 찾아봐", session_id="s1")

    assert plan.tool == "news_tool"


@pytest.mark.asyncio
async def test_detect_tool_recent_thing_not_mistaken_for_legal_basis():
    """"최근 거"가 공백 제거 후 "근거"로 오탐되어 LAW_RAG_TOOL로 잘못 분류되던 버그
    (실측: 뉴스 목록 후속질문 "그 중에 제일 최근 거 자세히 알려줘"가
    LAW_RAG_TOOL로 잘못 라우팅됨)"""
    with patch("app.services.question_router._load_session_context", new_callable=AsyncMock, return_value=""), \
         patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock, return_value="news_tool") as mock_llm:
        plan = await detect_tool("user1", "그 중에 제일 최근 거 자세히 알려줘", session_id="s1")

    mock_llm.assert_called_once()
    assert plan.tool == "news_tool"


@pytest.mark.asyncio
async def test_detect_tool_llm_non_law_tool():
    """LLM이 news_tool 선택 → 그대로 news_tool"""
    _llm_cache.clear()

    with patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.question_router._load_session_context", new_callable=AsyncMock, return_value=""):
        mock_llm.return_value = "news_tool"

        plan = await detect_tool("user1", "최근 산업재해 뉴스")

    assert plan.tool == "news_tool"
