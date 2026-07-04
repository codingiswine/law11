from typing import List, TypedDict

from langgraph.graph import StateGraph, END

from app.config import settings
from app.services.rag_service import get_embedding_async
from app.services import rag_grader
from app.tools import law_rag_tool, websearch_tool
from core.plan import ToolPlan
from core.stream import ToolChunk


class RagState(TypedDict):
    question: str
    contexts: List[str]
    answer: str
    hallucination_verdict: str
    relevance_verdict: str
    retry_count: int
    final_tool: str


async def retrieve(state: RagState) -> RagState:
    question = state["question"]

    embedding = await get_embedding_async(question)
    hits = await settings.qdrant_client.search(
        settings.QDRANT_COLLECTION_NAME,
        embedding,
        limit=5,
    )
    contexts = [h.payload.get("text", "") for h in hits if h.payload.get("text")]

    plan = ToolPlan(tool="law_rag_tool", args={"query": question})
    answer_parts: List[str] = []
    async for chunk in law_rag_tool.run(plan):
        if isinstance(chunk, ToolChunk) and chunk.type == "text":
            answer_parts.append(chunk.payload)

    return {
        **state,
        "contexts": contexts,
        "answer": "".join(answer_parts),
        "retry_count": state["retry_count"] + 1,
        "final_tool": "law_rag_tool",
    }


async def grade_hallucination_node(state: RagState) -> RagState:
    verdict = await rag_grader.grade_hallucination(
        state["question"], state["answer"], state["contexts"]
    )
    return {**state, "hallucination_verdict": verdict}


async def grade_relevance_node(state: RagState) -> RagState:
    verdict = await rag_grader.grade_relevance(state["question"], state["answer"])
    return {**state, "relevance_verdict": verdict}


async def websearch_fallback(state: RagState) -> RagState:
    plan = ToolPlan(tool="websearch_tool", args={"query": state["question"]})
    answer_parts: List[str] = []
    try:
        async for chunk in websearch_tool.run(plan):
            if isinstance(chunk, ToolChunk) and chunk.type == "text":
                answer_parts.append(chunk.payload)
        answer = "".join(answer_parts) if answer_parts else state["answer"]
    except Exception:
        answer = state["answer"]

    return {**state, "answer": answer, "final_tool": "websearch_tool"}


def route_after_hallucination(state: RagState) -> str:
    verdict = state.get("hallucination_verdict", "GROUNDED")
    if verdict in ("GROUNDED", "PARTIAL"):
        return "grade_relevance"
    if state["retry_count"] < 2:
        return "retrieve"
    return "websearch_fallback"


def route_after_relevance(state: RagState) -> str:
    if state.get("relevance_verdict") == "RELEVANT":
        return "end"
    return "websearch_fallback"


def create_self_rag_subgraph():
    graph = StateGraph(RagState)

    graph.add_node("retrieve", retrieve)
    graph.add_node("grade_hallucination", grade_hallucination_node)
    graph.add_node("grade_relevance", grade_relevance_node)
    graph.add_node("websearch_fallback", websearch_fallback)

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "grade_hallucination")
    graph.add_conditional_edges(
        "grade_hallucination",
        route_after_hallucination,
        {
            "grade_relevance": "grade_relevance",
            "retrieve": "retrieve",
            "websearch_fallback": "websearch_fallback",
        },
    )
    graph.add_conditional_edges(
        "grade_relevance",
        route_after_relevance,
        {
            "end": END,
            "websearch_fallback": "websearch_fallback",
        },
    )
    graph.add_edge("websearch_fallback", END)

    return graph.compile()
