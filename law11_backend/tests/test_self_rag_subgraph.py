import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.self_rag_subgraph import (
    RagState,
    retrieve,
    grade_hallucination_node,
    grade_relevance_node,
    websearch_fallback,
    route_after_hallucination,
    route_after_relevance,
)
from core.stream import ToolChunk


def _state(**kwargs) -> RagState:
    return {
        "question": "테스트 질문",
        "contexts": [],
        "answer": "",
        "hallucination_verdict": "",
        "relevance_verdict": "",
        "retry_count": 0,
        "final_tool": "law_rag_tool",
        **kwargs,
    }


# ── retrieve ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_collects_contexts_and_answer():
    mock_hit = MagicMock()
    mock_hit.payload = {"text": "산업안전보건법 제17조 내용"}

    async def _law_run(plan):
        yield ToolChunk(type="text", payload="GPT 답변 텍스트")
        yield ToolChunk(type="status", payload="완료")

    with patch("app.services.self_rag_subgraph.get_embedding_async", new_callable=AsyncMock, return_value=[0.1]*3072), \
         patch("app.services.self_rag_subgraph.settings") as mock_s, \
         patch("app.services.self_rag_subgraph.law_rag_tool") as mock_law:
        mock_s.qdrant_client.search = AsyncMock(return_value=[mock_hit])
        mock_s.QDRANT_COLLECTION_NAME = "laws"
        mock_law.run = _law_run

        result = await retrieve(_state())

    assert result["contexts"] == ["산업안전보건법 제17조 내용"]
    assert result["answer"] == "GPT 답변 텍스트"
    assert result["retry_count"] == 1
    assert result["final_tool"] == "law_rag_tool"


@pytest.mark.asyncio
async def test_retrieve_increments_retry_count():
    async def _law_run(plan):
        yield ToolChunk(type="text", payload="답변")

    with patch("app.services.self_rag_subgraph.get_embedding_async", new_callable=AsyncMock, return_value=[0.1]*3072), \
         patch("app.services.self_rag_subgraph.settings") as mock_s, \
         patch("app.services.self_rag_subgraph.law_rag_tool") as mock_law:
        mock_s.qdrant_client.search = AsyncMock(return_value=[])
        mock_s.QDRANT_COLLECTION_NAME = "laws"
        mock_law.run = _law_run

        result = await retrieve(_state(retry_count=1))

    assert result["retry_count"] == 2


@pytest.mark.asyncio
async def test_retrieve_skips_empty_context_payloads():
    mock_hit_valid = MagicMock()
    mock_hit_valid.payload = {"text": "조문 내용"}
    mock_hit_empty = MagicMock()
    mock_hit_empty.payload = {"text": ""}

    async def _law_run(plan):
        yield ToolChunk(type="text", payload="답변")

    with patch("app.services.self_rag_subgraph.get_embedding_async", new_callable=AsyncMock, return_value=[0.1]*3072), \
         patch("app.services.self_rag_subgraph.settings") as mock_s, \
         patch("app.services.self_rag_subgraph.law_rag_tool") as mock_law:
        mock_s.qdrant_client.search = AsyncMock(return_value=[mock_hit_valid, mock_hit_empty])
        mock_s.QDRANT_COLLECTION_NAME = "laws"
        mock_law.run = _law_run

        result = await retrieve(_state())

    assert result["contexts"] == ["조문 내용"]


# ── grade_hallucination_node ──────────────────────────────

@pytest.mark.asyncio
async def test_grade_hallucination_node_stores_verdict():
    with patch("app.services.self_rag_subgraph.rag_grader") as mock_grader:
        mock_grader.grade_hallucination = AsyncMock(return_value="HALLUCINATION")
        result = await grade_hallucination_node(_state(answer="잘못된 답변", contexts=["조문"]))
    assert result["hallucination_verdict"] == "HALLUCINATION"


# ── grade_relevance_node ──────────────────────────────────

@pytest.mark.asyncio
async def test_grade_relevance_node_stores_verdict():
    with patch("app.services.self_rag_subgraph.rag_grader") as mock_grader:
        mock_grader.grade_relevance = AsyncMock(return_value="NOT_RELEVANT")
        result = await grade_relevance_node(_state(answer="무관한 답변"))
    assert result["relevance_verdict"] == "NOT_RELEVANT"


# ── route_after_hallucination ─────────────────────────────

def test_route_grounded_goes_to_grade_relevance():
    assert route_after_hallucination(_state(hallucination_verdict="GROUNDED", retry_count=1)) == "grade_relevance"


def test_route_partial_goes_to_grade_relevance():
    assert route_after_hallucination(_state(hallucination_verdict="PARTIAL", retry_count=1)) == "grade_relevance"


def test_route_hallucination_retries_when_retry_lt_2():
    assert route_after_hallucination(_state(hallucination_verdict="HALLUCINATION", retry_count=1)) == "retrieve"


def test_route_hallucination_websearch_when_retry_gte_2():
    assert route_after_hallucination(_state(hallucination_verdict="HALLUCINATION", retry_count=2)) == "websearch_fallback"


# ── route_after_relevance ─────────────────────────────────

def test_route_relevant_returns_end():
    assert route_after_relevance(_state(relevance_verdict="RELEVANT")) == "end"


def test_route_not_relevant_returns_websearch():
    assert route_after_relevance(_state(relevance_verdict="NOT_RELEVANT")) == "websearch_fallback"


# ── websearch_fallback ────────────────────────────────────

@pytest.mark.asyncio
async def test_websearch_fallback_replaces_answer():
    async def _web_run(plan):
        yield ToolChunk(type="text", payload="웹 검색 결과")

    with patch("app.services.self_rag_subgraph.websearch_tool") as mock_web:
        mock_web.run = _web_run
        result = await websearch_fallback(_state(answer="기존 답변"))

    assert result["answer"] == "웹 검색 결과"
    assert result["final_tool"] == "websearch_tool"


@pytest.mark.asyncio
async def test_websearch_fallback_keeps_original_on_error():
    with patch("app.services.self_rag_subgraph.websearch_tool") as mock_web:
        mock_web.run = MagicMock(side_effect=Exception("web error"))
        result = await websearch_fallback(_state(answer="기존 답변"))

    assert result["answer"] == "기존 답변"
    assert result["final_tool"] == "websearch_tool"
