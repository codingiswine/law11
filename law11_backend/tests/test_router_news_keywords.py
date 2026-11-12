"""뉴스 fast-path가 도메인 일상어("사고")에 걸려 처벌 질문을 뉴스로 보내던 회귀 (#92).

실측: "중대재해처벌법에서 사업주가 사망사고를 내면 처벌이 어떻게 돼?"가
NEWS_TOOL로 가서 2022~2023년 기사 3건을 요약했다. 정답인 중대재해처벌법
제6조는 DB에 있었다. 원인 둘 — (a) _NEWS_KEYWORDS에 "사고·사건·이슈"처럼
산업안전 질문에 흔히 들어가는 단어가 있었고, (b) 줄임말 "중대재해처벌법"이
_CORE_LAWS에 없어 법령명 fast-path가 먼저 잡지 못했다.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.question_router import detect_tool

_NO_HISTORY = patch("app.services.question_router._load_session_context",
                    new_callable=AsyncMock, return_value="")


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "중대재해처벌법에서 사업주가 사망사고를 내면 처벌이 어떻게 돼?",
    "산안법상 추락사고 예방 조치는?",
])
async def test_accident_wording_with_law_name_goes_to_law_rag(question):
    with _NO_HISTORY, \
         patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock) as mock_llm:
        plan = await detect_tool("u", question)
    mock_llm.assert_not_called()
    assert plan.tool == "law_rag_tool"


@pytest.mark.asyncio
async def test_accident_wording_without_media_word_is_not_a_news_fast_path():
    """'사고'만으로는 뉴스를 단정할 수 없다 — LLM 분류로 넘긴다."""
    with _NO_HISTORY, \
         patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock,
               return_value="law_rag_tool") as mock_llm:
        plan = await detect_tool("u", "작업 중 사고가 나면 사업주는 뭘 해야 해?")
    mock_llm.assert_called_once()
    assert plan.tool == "law_rag_tool"


@pytest.mark.asyncio
@pytest.mark.parametrize("question", [
    "최근 산업재해 뉴스 알려줘",
    "최신 중대재해 보도 있나요?",
    "계단 관련 사고 기사 찾아봐",
])
async def test_explicit_media_words_still_fast_path_to_news(question):
    with _NO_HISTORY, \
         patch("app.services.question_router._classify_with_llm", new_callable=AsyncMock) as mock_llm:
        plan = await detect_tool("u", question)
    mock_llm.assert_not_called()
    assert plan.tool == "news_tool"
