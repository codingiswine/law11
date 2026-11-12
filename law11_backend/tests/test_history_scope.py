"""/api/history가 브라우저가 가진 세션 ID 밖의 대화를 돌려주지 않는다 (#81).

user_id 필터는 모든 방문자가 같은 상수("law11_user")라 필터가 아니었다 — 사이드바가
전체 방문자의 대화를 받아 그렸다. 여기서는 세 가지를 고정한다:
(1) ID를 안 넘기면 DB에 가지도 않는다, (2) 넘긴 ID로만 건다, (3) user_id는 조건이 아니다.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import routes


def _engine(rows=()):
    conn = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = list(rows)
    conn.execute = AsyncMock(return_value=result)

    engine = MagicMock()

    @asynccontextmanager
    async def begin():
        yield conn

    engine.begin = begin
    return engine, conn


@pytest.mark.asyncio
async def test_no_session_ids_returns_empty_without_touching_db(monkeypatch):
    engine, conn = _engine()
    monkeypatch.setattr(routes, "async_engine", engine)

    assert await routes.get_chat_history(session_ids="") == {"total": 0, "history": []}
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_history_is_scoped_to_the_given_session_ids(monkeypatch):
    engine, conn = _engine()
    monkeypatch.setattr(routes, "async_engine", engine)

    await routes.get_chat_history(session_ids="s1,s2,,s3")

    sql, params = conn.execute.call_args.args
    assert params["ids"] == ["s1", "s2", "s3"]
    assert "session_id IN" in str(sql)
    assert "user_id" not in str(sql), "user_id는 모든 방문자가 같은 상수라 필터가 아니다"


@pytest.mark.asyncio
async def test_session_id_count_is_capped(monkeypatch):
    engine, conn = _engine()
    monkeypatch.setattr(routes, "async_engine", engine)

    ids = ",".join(f"s{i}" for i in range(routes.MAX_HISTORY_SESSIONS + 50))
    await routes.get_chat_history(session_ids=ids)

    assert len(conn.execute.call_args.args[1]["ids"]) == routes.MAX_HISTORY_SESSIONS
