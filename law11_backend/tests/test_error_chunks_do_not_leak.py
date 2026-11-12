"""툴이 직접 yield하는 error 청크에 예외 원문이 실리지 않는다 (#83).

#31/#66은 run_tool 밖으로 raise된 예외와 HTTP 500만 가렸다. general_tool과
db_query_tool_async는 예외를 잡아 `f"... {str(e)}"`로 **직접 yield**했고, 그 청크는
routes.event_stream이 그대로 SSE로 내보낸다 — OpenAI 인증 오류의 키 접두어,
asyncpg 오류의 테이블명이 사용자 화면에 갔다.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.tools import db_query_tool_async, general_tool
from core.plan import ToolPlan

SECRET_FRAGMENT = "sk-proj-SECRET123"
TABLE_FRAGMENT = 'relation "chat_history"'


def _error_payloads(chunks):
    return [c.payload for c in chunks if c.type == "error"]


@pytest.mark.asyncio
async def test_general_tool_error_chunk_hides_the_exception_text():
    plan = ToolPlan(tool="general_tool", args={"query": "안녕"})
    with patch("app.tools.general_tool.settings") as s:
        s.openai_client.chat.completions.create = AsyncMock(
            side_effect=Exception(f"Incorrect API key provided: {SECRET_FRAGMENT}"))
        chunks = [c async for c in general_tool.run(plan)]

    errors = _error_payloads(chunks)
    assert errors, "오류가 났는데 error 청크가 없다"
    assert all(SECRET_FRAGMENT not in p for p in errors), f"예외 원문이 사용자 청크에 실렸다: {errors}"


@pytest.mark.asyncio
async def test_db_query_tool_error_chunk_hides_the_exception_text():
    plan = ToolPlan(tool="db_query_tool_async", args={"query": "비계 기록에서 확인해줘"})
    with patch("app.tools.db_query_tool_async.run_db_query_tool",
               AsyncMock(side_effect=Exception(f"{TABLE_FRAGMENT} does not exist"))):
        chunks = [c async for c in db_query_tool_async.run(plan)]

    errors = _error_payloads(chunks)
    assert errors, "오류가 났는데 error 청크가 없다"
    assert all(TABLE_FRAGMENT not in p for p in errors), f"예외 원문이 사용자 청크에 실렸다: {errors}"
