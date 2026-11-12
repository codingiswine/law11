"""실험 경로(/ask-multi)의 배선 결함 세 가지를 고정한다 (#89).

(1) 판례 툴이 _ROUTING_MAP에 없어 판례 질문이 general_agent로 갔다.
(2) _make_tool_node가 router의 plan.args를 버려 세션 history(context)가 툴에 닿지 않았다.
(3) law_agent_node가 요청마다 Self-RAG 서브그래프를 다시 compile했다.
(4) Self-RAG retrieve가 운영 경로와 다른 조문(필터 없는 Qdrant top-5)으로 채점했다.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import langgraph_multi_agent as mag
from app.services import self_rag_subgraph
from core.stream import ToolChunk


def test_case_law_questions_route_to_the_case_agent_and_the_node_exists():
    assert mag.route_to_agent({"selected_tool": "case_law_rag_tool"}) == "case_agent"
    assert "case_agent" in mag._graph.nodes, "맵에만 있고 그래프에 노드가 없다"


@pytest.mark.asyncio
async def test_tool_nodes_receive_the_router_context():
    captured = {}

    async def _run(plan):
        captured["plan"] = plan
        yield ToolChunk(type="text", payload="ok")

    node = mag._make_tool_node(SimpleNamespace(run=_run), "websearch_tool", "test")
    await node({"question": "그거 안 지키면 처벌은?", "session_id": "s",
                "tool_args": {"query": "그거 안 지키면 처벌은?", "context": "사용자: 비계 설치 안전 기준 알려줘"}})

    assert captured["plan"].args.get("context") == "사용자: 비계 설치 안전 기준 알려줘", "router의 context가 툴에 닿지 않았다"
    assert captured["plan"].args["session_id"] == "s"


@pytest.mark.asyncio
async def test_law_agent_does_not_recompile_the_subgraph_per_request():
    graph = AsyncMock()
    graph.ainvoke.return_value = {"answer": "a", "final_tool": "law_rag_tool"}
    factory = MagicMock()
    with patch.object(mag, "_self_rag", graph), patch.object(mag, "create_self_rag_subgraph", factory):
        await mag.law_agent_node({"question": "q", "metadata": {}})
    factory.assert_not_called()
    graph.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_self_rag_grades_against_the_articles_the_search_actually_found():
    found = SimpleNamespace(articles=[{"text": "제17조 본문", "score": 1.0}, {"text": "", "score": 0.9}])

    async def _run(plan):
        yield ToolChunk(type="text", payload="답")

    fake_tool = SimpleNamespace(search_law_articles=AsyncMock(return_value=found), run=_run)
    with patch.object(self_rag_subgraph, "law_rag_tool", fake_tool):
        state = await self_rag_subgraph.retrieve({"question": "산업안전보건법 제17조", "contexts": [],
                                                  "answer": "", "hallucination_verdict": "",
                                                  "relevance_verdict": "", "retry_count": 0,
                                                  "final_tool": "law_rag_tool"})
    assert state["contexts"] == ["제17조 본문"], "채점 컨텍스트가 운영 검색 결과가 아니다"
    fake_tool.search_law_articles.assert_awaited_once_with("산업안전보건법 제17조")
