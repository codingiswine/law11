import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.langgraph_multi_agent import law_agent_node


def _state(**kwargs):
    return {
        "question": "산업안전보건법 위반 시 처벌은?",
        "user_id": "user1",
        "selected_tool": "law_rag_tool",
        "answer_chunks": [],
        "final_answer": "",
        "metadata": {},
        **kwargs,
    }


@pytest.mark.asyncio
async def test_law_agent_node_returns_subgraph_answer():
    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {
        "answer": "위반 시 5년 이하 징역",
        "final_tool": "law_rag_tool",
    }
    mock_factory = MagicMock(return_value=mock_graph)

    with patch("app.services.langgraph_multi_agent.create_self_rag_subgraph", mock_factory):
        result = await law_agent_node(_state())

    assert result["final_answer"] == "위반 시 5년 이하 징역"
    assert result["metadata"]["final_tool"] == "law_rag_tool"


@pytest.mark.asyncio
async def test_law_agent_node_passes_question_to_subgraph():
    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {"answer": "답변", "final_tool": "law_rag_tool"}
    mock_factory = MagicMock(return_value=mock_graph)

    with patch("app.services.langgraph_multi_agent.create_self_rag_subgraph", mock_factory):
        await law_agent_node(_state(question="특정 질문"))

    call_args = mock_graph.ainvoke.call_args[0][0]
    assert call_args["question"] == "특정 질문"


@pytest.mark.asyncio
async def test_law_agent_node_websearch_fallback_reflected_in_metadata():
    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {
        "answer": "웹 검색으로 찾은 답변",
        "final_tool": "websearch_tool",
    }
    mock_factory = MagicMock(return_value=mock_graph)

    with patch("app.services.langgraph_multi_agent.create_self_rag_subgraph", mock_factory):
        result = await law_agent_node(_state())

    assert result["final_answer"] == "웹 검색으로 찾은 답변"
    assert result["metadata"]["final_tool"] == "websearch_tool"
