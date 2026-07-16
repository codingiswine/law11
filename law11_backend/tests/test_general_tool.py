import pytest
from unittest.mock import AsyncMock, patch

from core.plan import ToolPlan
from app.tools import general_tool


@pytest.mark.asyncio
async def test_run_includes_context_in_prompt_when_present():
    """회귀 테스트: general_tool이 plan.args["context"]를 무시하고 현재 질문만
    보내던 버그 — system_msg는 "이전 대화 내용을 참고해"라고 지시하면서 실제로는
    context를 한 번도 안 읽었음 (실측: "비계 설치 안전 기준" 질문 후 "그거 다
    지키려니까 힘들다"를 물으면 "그거"가 뭔지 몰라 일반론만 답했음)."""
    plan = ToolPlan(tool="general_tool", args={"query": "그거 다 지키려니까 힘들다", "context": "사용자: 비계 설치 안전 기준 알려줘"})

    captured = {}

    async def _fake_stream(*args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        class _Stream:
            def __aiter__(self): return self
            async def __anext__(self): raise StopAsyncIteration
        return _Stream()

    with patch("app.tools.general_tool.settings") as mock_settings:
        mock_settings.openai_client.chat.completions.create = _fake_stream
        async for _ in general_tool.run(plan):
            pass

    user_message = captured["messages"][1]["content"]
    assert "비계 설치 안전 기준" in user_message


@pytest.mark.asyncio
async def test_run_without_context_still_works():
    plan = ToolPlan(tool="general_tool", args={"query": "고마워"})

    async def _fake_stream(*args, **kwargs):
        class _Stream:
            def __aiter__(self): return self
            async def __anext__(self): raise StopAsyncIteration
        return _Stream()

    with patch("app.tools.general_tool.settings") as mock_settings:
        mock_settings.openai_client.chat.completions.create = _fake_stream
        chunks = [c async for c in general_tool.run(plan)]

    assert any(c.type == "status" for c in chunks)
