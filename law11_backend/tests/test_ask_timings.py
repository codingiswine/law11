"""
/ask 스트림의 단계별 타이밍 계측 검증.

status 청크 도착 시각으로 단계 경계를 잡고, 첫 text 청크로 생성 시작을 잡는다.
tool 코드는 건드리지 않으므로 여기서 깨지면 routes.py의 계측 로직 문제다.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from app.api.models import QueryRequest
from app.api.routes import ask_law11
from core.stream import ToolChunk

SEARCH_SEC = 0.05   # 검색 구간 흉내
GEN_SEC = 0.05      # 생성 구간 흉내

META = {
    "query_type": "semantic",
    "selected_source": "qdrant",
    "selected_articles": ["산업안전보건법 제38조"],
    "fallback_used": False,
    "confidence_score": 0.82,
    "tool": "law_rag_tool",
    "citations": [],
}


async def _fake_run_tool(plan):
    yield ToolChunk(type="status", payload="⚖️ 법령 검색 시작...")
    await asyncio.sleep(SEARCH_SEC)
    yield ToolChunk(type="status", payload="🧠 [Qdrant] 벡터 검색 중...")
    yield ToolChunk(type="meta", payload=META)
    yield ToolChunk(type="status", payload="🧠 GPT 요약 중...")
    yield ToolChunk(type="text", payload="제38조는 ")
    await asyncio.sleep(GEN_SEC)
    yield ToolChunk(type="text", payload="다음과 같습니다.")


async def _drain(resp):
    async for _ in resp.body_iterator:
        pass


@pytest.mark.asyncio
async def test_timings_recorded_with_stage_timeline():
    plan = type("P", (), {"tool": "law_rag_tool", "summary": lambda self: "law_rag_tool"})()

    with patch("app.api.routes._detect_tool", AsyncMock(return_value=plan)), \
         patch("app.api.routes.run_tool", _fake_run_tool), \
         patch("app.api.routes.save_chat_history", AsyncMock(return_value=1)), \
         patch("app.api.routes.save_citations", AsyncMock()), \
         patch("app.api.routes.qa_logger.log_request") as mock_log:
        resp = await ask_law11(QueryRequest(question="제38조 알려줘"))
        await _drain(resp)

    mock_log.assert_called_once()
    t = mock_log.call_args.kwargs["timings"]

    # 단계 경계가 status 청크 수만큼 잡혔는가
    assert [s["label"] for s in t["stages"]] == [
        "⚖️ 법령 검색 시작...",
        "🧠 [Qdrant] 벡터 검색 중...",
        "🧠 GPT 요약 중...",
    ]

    # 검색 구간이 첫 토큰 이전에 반영됐는가
    assert t["first_token"] >= SEARCH_SEC
    # 생성 구간이 첫 토큰 이후로 분리됐는가 — 이게 깨지면 "11초 중 생성 X초"를 못 말한다
    assert t["generation"] >= GEN_SEC
    assert t["tool_total"] >= SEARCH_SEC + GEN_SEC
    assert t["total"] >= t["tool_total"]        # 라우팅 시간이 더해졌는가
    assert t["routing"] is not None


@pytest.mark.asyncio
async def test_no_meta_chunk_skips_logging():
    """meta 없이 끝나는 턴(도구 실패)은 기록하지 않는다 — 빈 행 오염 방지."""
    plan = type("P", (), {"tool": "general_tool", "summary": lambda self: "general_tool"})()

    async def _no_meta(plan):
        yield ToolChunk(type="status", payload="⚠️ 실패")

    with patch("app.api.routes._detect_tool", AsyncMock(return_value=plan)), \
         patch("app.api.routes.run_tool", _no_meta), \
         patch("app.api.routes.qa_logger.log_request") as mock_log:
        resp = await ask_law11(QueryRequest(question="아무거나"))
        await _drain(resp)

    mock_log.assert_not_called()
