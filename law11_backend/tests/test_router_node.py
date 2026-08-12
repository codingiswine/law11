import pytest
from unittest.mock import AsyncMock, patch

from app.services.langgraph_multi_agent import router_node
from core.plan import ToolPlan


def _state(**kwargs):
    return {
        "question": "그거가 정확히 뭐였는지 다시 말해줘",
        "user_id": "user1",
        "session_id": "sess-A",
        "selected_tool": "",
        "answer_chunks": [],
        "final_answer": "",
        "metadata": {},
        **kwargs,
    }


@pytest.mark.asyncio
async def test_router_node_forwards_session_id_to_detect_tool():
    """회귀 잠금: router_node가 session_id를 안 넘기면 /ask-multi 경로에서
    후속질문 라우팅이 세션 히스토리 없이 이뤄진다 (코드리뷰에서 발견)."""
    mock_detect = AsyncMock(return_value=ToolPlan(tool="db_query_tool_async", args={}))

    with patch("app.services.langgraph_multi_agent._detect_tool", mock_detect):
        await router_node(_state())

    mock_detect.assert_awaited_once_with("user1", "그거가 정확히 뭐였는지 다시 말해줘", "sess-A")
