from typing import List, TypedDict

from langgraph.graph import StateGraph, END

from app.services.question_router import detect_tool as _detect_tool
from app.services.self_rag_subgraph import create_self_rag_subgraph
from app.tools import (
    law_rag_tool,
    news_tool,
    blog_tool,
    general_tool,
    db_query_tool_async,
    websearch_tool,
)
from core.logger import logger
from core.plan import ToolPlan


class AgentState(TypedDict):
    """그래프 전체에서 공유되는 상태. 노드는 이 dict를 수정하지 않고 새 dict를 반환한다."""
    question: str
    user_id: str
    selected_tool: str
    answer_chunks: List[str]
    final_answer: str
    metadata: dict


# ── 노드 ────────────────────────────────────────────────────────────

async def router_node(state: AgentState) -> AgentState:
    """question_router로 tool을 선택하고 selected_tool에 저장한다."""
    logger.info(f"🔀 [Router] 질문 분석: {state['question']}")
    plan: ToolPlan = await _detect_tool(state["user_id"], state["question"])
    logger.info(f"🎯 [Router] 선택된 Tool: {plan.tool}")
    return {**state, "selected_tool": plan.tool, "metadata": {"plan": plan.summary()}}


async def law_agent_node(state: AgentState) -> AgentState:
    """Self-RAG 서브그래프를 통해 법령 RAG 답변과 할루시네이션 검증을 수행한다."""
    logger.info("🏛️ [Law Agent] Self-RAG 서브그래프 시작")
    subgraph = create_self_rag_subgraph()
    result = await subgraph.ainvoke({
        "question": state["question"],
        "contexts": [],
        "answer": "",
        "hallucination_verdict": "",
        "relevance_verdict": "",
        "retry_count": 0,
        "final_tool": "law_rag_tool",
    })
    logger.info(f"🏛️ [Law Agent] 완료 (final_tool={result['final_tool']})")
    return {
        **state,
        "final_answer": result["answer"],
        "metadata": {**state.get("metadata", {}), "final_tool": result["final_tool"]},
    }


def _make_tool_node(tool_module, tool_name: str, label: str):
    """news/blog/db/web/general 5개 노드의 공통 패턴을 클로저로 캡처해 반환한다.
    패턴: ToolPlan 생성 → tool.run() 스트리밍 → type=="text" 청크만 수집 → join.
    """
    async def _node(state: AgentState) -> AgentState:
        logger.info(f"{label} 시작")
        plan = ToolPlan(tool=tool_name, args={"query": state["question"]})
        chunks = [c.payload async for c in tool_module.run(plan) if c.type == "text"]
        logger.info(f"{label} 완료")
        return {**state, "answer_chunks": chunks, "final_answer": "".join(chunks)}
    return _node


news_agent_node    = _make_tool_node(news_tool,           "news_tool",           "📰 [News Agent]")
blog_agent_node    = _make_tool_node(blog_tool,           "blog_tool",           "📝 [Blog Agent]")
db_agent_node      = _make_tool_node(db_query_tool_async, "db_query_tool_async", "💾 [DB Agent]")
web_agent_node     = _make_tool_node(websearch_tool,      "websearch_tool",      "🌐 [Web Agent]")
general_agent_node = _make_tool_node(general_tool,        "general_tool",        "💬 [General Agent]")


# ── 라우팅 ───────────────────────────────────────────────────────────

_ROUTING_MAP = {
    "law_rag_tool":        "law_agent",
    "news_tool":           "news_agent",
    "blog_tool":           "blog_agent",
    "db_query_tool_async": "db_agent",
    "websearch_tool":      "web_agent",
    "general_tool":        "general_agent",
}


def route_to_agent(state: AgentState) -> str:
    """selected_tool을 보고 실행할 agent 노드 이름을 반환한다."""
    tool = state["selected_tool"]
    target = _ROUTING_MAP.get(tool, "general_agent")
    logger.info(f"🔀 [Routing] {tool} → {target}")
    return target


# ── 그래프 빌드 (모듈 로드 시 1회만 컴파일) ────────────────────────

def _build_graph():
    """StateGraph를 조립하고 compile()한다.
    모듈 임포트 시 _graph = _build_graph()로 1회만 호출된다.
    compile()은 비용이 크므로 요청마다 재실행하지 않는다.
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("router",        router_node)
    workflow.add_node("law_agent",     law_agent_node)
    workflow.add_node("news_agent",    news_agent_node)
    workflow.add_node("blog_agent",    blog_agent_node)
    workflow.add_node("db_agent",      db_agent_node)
    workflow.add_node("web_agent",     web_agent_node)
    workflow.add_node("general_agent", general_agent_node)

    workflow.set_entry_point("router")
    workflow.add_conditional_edges("router", route_to_agent, {v: v for v in _ROUTING_MAP.values()})

    for agent in _ROUTING_MAP.values():
        workflow.add_edge(agent, END)

    return workflow.compile()


# ponytail: compile once at import — LangGraph compile() is expensive per-request
_graph = _build_graph()
logger.info("✅ [LangGraph] Multi-Agent Graph 생성 완료")


# ── 공개 API ─────────────────────────────────────────────────────────

async def run_multi_agent(user_id: str, question: str) -> AgentState:
    """Multi-Agent 그래프를 실행하고 최종 state를 반환한다."""
    logger.info(f"🚀 [Multi-Agent] 시작: {question}")
    final_state = await _graph.ainvoke(AgentState(
        question=question,
        user_id=user_id,
        selected_tool="",
        answer_chunks=[],
        final_answer="",
        metadata={},
    ))
    logger.info("✅ [Multi-Agent] 완료")
    return final_state


__all__ = ["run_multi_agent", "AgentState"]
