import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.rag_grader import grade_hallucination, grade_relevance


def _mock_openai_response(json_str: str):
    mock = MagicMock()
    mock.choices[0].message.content = json_str
    return mock


@pytest.mark.asyncio
async def test_grade_hallucination_grounded():
    with patch("app.services.rag_grader.settings") as s:
        s.openai_client.chat.completions.create = AsyncMock(
            return_value=_mock_openai_response('{"verdict": "GROUNDED"}')
        )
        result = await grade_hallucination("질문", "답변", ["조문1"])
    assert result == "GROUNDED"


@pytest.mark.asyncio
async def test_grade_hallucination_hallucination():
    with patch("app.services.rag_grader.settings") as s:
        s.openai_client.chat.completions.create = AsyncMock(
            return_value=_mock_openai_response('{"verdict": "HALLUCINATION"}')
        )
        result = await grade_hallucination("질문", "잘못된 답변", ["조문1"])
    assert result == "HALLUCINATION"


@pytest.mark.asyncio
async def test_grade_hallucination_error_returns_grounded():
    with patch("app.services.rag_grader.settings") as s:
        s.openai_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        result = await grade_hallucination("질문", "답변", ["조문1"])
    assert result == "GROUNDED"


@pytest.mark.asyncio
async def test_grade_hallucination_unknown_verdict_returns_grounded():
    with patch("app.services.rag_grader.settings") as s:
        s.openai_client.chat.completions.create = AsyncMock(
            return_value=_mock_openai_response('{"verdict": "UNKNOWN_VALUE"}')
        )
        result = await grade_hallucination("질문", "답변", ["조문1"])
    assert result == "GROUNDED"


@pytest.mark.asyncio
async def test_grade_relevance_relevant():
    with patch("app.services.rag_grader.settings") as s:
        s.openai_client.chat.completions.create = AsyncMock(
            return_value=_mock_openai_response('{"verdict": "RELEVANT"}')
        )
        result = await grade_relevance("질문", "관련 답변")
    assert result == "RELEVANT"


@pytest.mark.asyncio
async def test_grade_relevance_not_relevant():
    with patch("app.services.rag_grader.settings") as s:
        s.openai_client.chat.completions.create = AsyncMock(
            return_value=_mock_openai_response('{"verdict": "NOT_RELEVANT"}')
        )
        result = await grade_relevance("법령 질문", "피자 이야기")
    assert result == "NOT_RELEVANT"


@pytest.mark.asyncio
async def test_grade_relevance_error_returns_relevant():
    with patch("app.services.rag_grader.settings") as s:
        s.openai_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        result = await grade_relevance("질문", "답변")
    assert result == "RELEVANT"
