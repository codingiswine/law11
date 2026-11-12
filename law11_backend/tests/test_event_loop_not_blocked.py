"""요청 경로의 디스크 I/O가 이벤트 루프를 세우지 않는다 (#87).

임베딩 캐시(sqlite3)와 요청 로그(JSONL append)는 동기 I/O다. 루프에서 직접 부르면
그 시간 동안 **다른 사용자의 SSE 토큰 스트림이 전부 멈춘다**. 여기서는 그 I/O를
0.2초 블로킹으로 바꿔 놓고, 옆에서 10ms마다 도는 틱 카운터가 계속 돌았는지 본다 —
루프가 막히면 틱은 0~1에서 멈춘다.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.api.models import QueryRequest
from app.api.routes import ask_law11
from app.services.embedding_cache import get_embedding_async
from core.stream import ToolChunk

BLOCK_SEC = 0.2
MIN_TICKS = 5          # 0.2초 동안 10ms 틱이면 ~20회. 막히면 0~1회.


async def _ticker(stop: asyncio.Event) -> int:
    n = 0
    while not stop.is_set():
        await asyncio.sleep(0.01)
        n += 1
    return n


async def _run_with_ticker(coro):
    stop = asyncio.Event()
    ticks = asyncio.create_task(_ticker(stop))
    try:
        return await coro, await _finish(stop, ticks)
    finally:
        stop.set()


async def _finish(stop, ticks):
    stop.set()
    return await ticks


def _blocking_lookup(_query):
    time.sleep(BLOCK_SEC)
    return [0.3] * 4


@pytest.mark.asyncio
async def test_embedding_cache_lookup_runs_off_the_event_loop():
    with patch("app.services.embedding_cache._get_cached_embedding", _blocking_lookup):
        result, ticks = await _run_with_ticker(get_embedding_async("비계 설치 기준"))
    assert result == [0.3] * 4
    assert ticks >= MIN_TICKS, f"sqlite 조회가 루프를 {BLOCK_SEC}s 막았다 (ticks={ticks})"


# ── qa_logger.log_request (routes.event_stream 안에서 호출) ─────────────────

def _req() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/ask", "headers": [],
                    "client": ("127.0.0.1", 0)})


async def _fake_run_tool(_plan):
    yield ToolChunk(type="meta", payload={
        "query_type": "semantic", "selected_source": "qdrant", "selected_articles": [],
        "fallback_used": False, "confidence_score": 0.5, "tool": "law_rag_tool", "citations": [],
    })
    yield ToolChunk(type="text", payload="답")


def _blocking_log(**_kw):
    time.sleep(BLOCK_SEC)


async def _drain(resp):
    async for _ in resp.body_iterator:
        pass


@pytest.mark.asyncio
async def test_request_log_append_runs_off_the_event_loop():
    plan = type("P", (), {"tool": "law_rag_tool", "summary": lambda self: "law_rag_tool"})()
    with patch("app.api.routes._detect_tool", AsyncMock(return_value=plan)), \
         patch("app.api.routes.run_tool", _fake_run_tool), \
         patch("app.api.routes.save_chat_history", AsyncMock(return_value=1)), \
         patch("app.api.routes.save_citations", AsyncMock()), \
         patch("app.api.routes.qa_logger.log_request", _blocking_log):
        resp = await ask_law11(_req(), QueryRequest(question="비계"))
        _, ticks = await _run_with_ticker(_drain(resp))
    assert ticks >= MIN_TICKS, f"JSONL append가 루프를 {BLOCK_SEC}s 막았다 (ticks={ticks})"
