from typing import List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from app.services.question_router import detect_tool as _detect_tool
from app.services.self_rag_subgraph import create_self_rag_subgraph
from app.tools import (
    law_rag_tool,
    case_law_rag_tool,
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
    session_id: str
    selected_tool: str
    tool_args: dict          # router가 만든 ToolPlan.args — 세션 history(context)가 여기 실려 온다 (#89)
    answer_chunks: List[str]
    final_answer: str
    metadata: dict


# ── 노드 ────────────────────────────────────────────────────────────

async def router_node(state: AgentState) -> AgentState:
    """question_router로 tool을 선택하고 selected_tool·tool_args에 저장한다."""
    logger.info(f"🔀 [Router] 질문 분석: {state['question']}")
    plan: ToolPlan = await _detect_tool(state["user_id"], state["question"], state.get("session_id"))
    logger.info(f"🎯 [Router] 선택된 Tool: {plan.tool}")
    # ⚠️ 예전엔 plan.tool만 넘기고 plan.args를 버렸다 — detect_tool이 세션 history를 args["context"]에
    # 실어 주는데, 아래 _make_tool_node가 ToolPlan을 새로 만들며 context 없이 툴을 불렀다 (#89).
    return {**state, "selected_tool": plan.tool, "tool_args": dict(plan.args), "metadata": {"plan": plan.summary()}}


# ponytail: 서브그래프도 import 시 1회 compile — 아래 _graph와 같은 이유. 요청마다 compile()하던 것을 고침 (#89)
_self_rag = create_self_rag_subgraph()


async def law_agent_node(state: AgentState) -> AgentState:
    """Self-RAG 서브그래프를 통해 법령 RAG 답변과 할루시네이션 검증을 수행한다."""
    logger.info("🏛️ [Law Agent] Self-RAG 서브그래프 시작")
    result = await _self_rag.ainvoke({
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
        # router가 넘긴 args(context 포함)를 바탕으로 query·session_id만 보장한다 (#89)
        args = {**state.get("tool_args", {}), "query": state["question"], "session_id": state.get("session_id", "")}
        plan = ToolPlan(tool=tool_name, args=args)
        chunks = [c.payload async for c in tool_module.run(plan) if c.type == "text"]
        logger.info(f"{label} 완료")
        return {**state, "answer_chunks": chunks, "final_answer": "".join(chunks)}
    return _node


case_agent_node    = _make_tool_node(case_law_rag_tool,   "case_law_rag_tool",   "⚖️ [Case Agent]")
news_agent_node    = _make_tool_node(news_tool,           "news_tool",           "📰 [News Agent]")
blog_agent_node    = _make_tool_node(blog_tool,           "blog_tool",           "📝 [Blog Agent]")
db_agent_node      = _make_tool_node(db_query_tool_async, "db_query_tool_async", "💾 [DB Agent]")
web_agent_node     = _make_tool_node(websearch_tool,      "websearch_tool",      "🌐 [Web Agent]")
general_agent_node = _make_tool_node(general_tool,        "general_tool",        "💬 [General Agent]")


# ── 라우팅 ───────────────────────────────────────────────────────────

_ROUTING_MAP = {
    "law_rag_tool":        "law_agent",
    "case_law_rag_tool":   "case_agent",   # #38에서 툴을 추가할 때 이 맵이 빠져 판례 질문이 general_agent로 갔다 (#89)
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
    workflow.add_node("case_agent",    case_agent_node)
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

async def run_multi_agent(user_id: str, question: str, session_id: Optional[str] = None) -> AgentState:
    """Multi-Agent 그래프를 실행하고 최종 state를 반환한다."""
    logger.info(f"🚀 [Multi-Agent] 시작: {question}")
    final_state = await _graph.ainvoke(AgentState(
        question=question,
        user_id=user_id,
        session_id=session_id or "",
        selected_tool="",
        tool_args={},
        answer_chunks=[],
        final_answer="",
        metadata={},
    ))
    logger.info("✅ [Multi-Agent] 완료")
    return final_state


__all__ = ["run_multi_agent", "AgentState"]
