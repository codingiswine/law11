"""같은 세션의 연속 저장이 turn_index를 공유하지 않는다 (#85).

chat_history는 user 행(turn_index)과 assistant 행(turn_index+1)으로 짝을 맺고,
db_query_tool이 그 +1 관계로 self-join한다. turn_index가 int(time.time())이라
1초 안에 두 번 저장되면 (T, T+1), (T, T+1)이 겹쳐 Q1이 A2와도 짝지어졌다 —
"이전 대화 기록" 답변에 남의 답이 붙는다. 여기서는 두 저장을 바로 이어 호출해
네 turn_index가 전부 다른지 본다. 1초 해상도면 이 테스트는 거의 항상 실패한다.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import routes


def _engine(captured):
    conn = MagicMock()

    async def _execute(_sql, params):
        captured.append(params)
        result = MagicMock()
        result.scalar_one.return_value = 1
        return result

    conn.execute = AsyncMock(side_effect=_execute)
    engine = MagicMock()

    @asynccontextmanager
    async def begin():
        yield conn

    engine.begin = begin
    return engine


@pytest.mark.asyncio
async def test_back_to_back_saves_never_share_a_turn_index(monkeypatch):
    captured = []
    monkeypatch.setattr(routes, "async_engine", _engine(captured))

    await routes.save_chat_history("u", "Q1", "A1", "law_rag_tool", session_id="s")
    await routes.save_chat_history("u", "Q2", "A2", "law_rag_tool", session_id="s")

    by_call = [captured[0:2], captured[2:4]]
    for user_row, assistant_row in by_call:
        assert user_row["role"] == "user" and assistant_row["role"] == "assistant"
        assert assistant_row["turn_index"] == user_row["turn_index"] + 1, "짝 규칙(+1)이 깨졌다"

    indices = [p["turn_index"] for p in captured]
    assert len(set(indices)) == 4, f"두 저장이 turn_index를 공유했다: {indices}"
