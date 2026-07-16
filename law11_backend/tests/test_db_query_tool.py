import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.db_query_tool_async import _extract_search_term, run_db_query_tool


def test_extract_search_term_strips_trigger_and_request_verb():
    """"비계 기록에서 확인해줘" → "비계"만 남아야 함
    (회귀 테스트: 트리거 키워드만 지우면 "확인해줘"가 남아 과거 메시지와
    전체 문자열 매치가 실패하던 버그)"""
    assert _extract_search_term("비계 기록에서 확인해줘") == "비계"


def test_extract_search_term_strips_db_keyword_only():
    assert _extract_search_term("안전관리자 선임 기준 데이터에서 찾아줘") == "안전관리자 선임 기준"


def test_extract_search_term_no_trigger_words_unchanged():
    assert _extract_search_term("비계") == "비계"


def _mock_engine(execute_side_effect):
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = execute_side_effect
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_ctx)
    return mock_engine, mock_conn


def _fake_result(rows):
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


@pytest.mark.asyncio
async def test_run_db_query_tool_falls_back_to_recent_history_when_keyword_search_empty():
    """회귀 테스트: "다시 말해줘" 같은 자연어 재확인 요청은 어떤 트리거/요청동사
    목록에도 안 걸려 검색어가 문장 전체로 남는다 — 키워드 검색이 0건이면
    최근 대화로 폴백해야 한다 (실측: "그거가 정확히 뭐였는지 다시 말해줘"가
    "❌ DB에서 결과를 찾을 수 없습니다"만 반환했음)."""
    recent_row = MagicMock()
    recent_row._mapping = {"question": "비계 설치 안전 기준 알려줘", "answer": "...", "created_at": "2026-07-16"}

    engine, conn = _mock_engine([_fake_result([]), _fake_result([recent_row])])

    with patch("app.tools.db_query_tool_async.settings") as mock_settings:
        mock_settings.async_engine = engine
        results = await run_db_query_tool("그거가 정확히 뭐였는지 다시 말해줘")

    assert conn.execute.call_count == 2
    assert results == [{"question": "비계 설치 안전 기준 알려줘", "answer": "...", "created_at": "2026-07-16"}]


@pytest.mark.asyncio
async def test_run_db_query_tool_uses_keyword_match_when_found():
    """키워드 검색이 실제로 매치되면 폴백(두 번째 쿼리)까지 가지 않아야 함."""
    matched_row = MagicMock()
    matched_row._mapping = {"question": "비계 기록에서 확인해줘", "answer": "...", "created_at": "2026-07-16"}

    engine, conn = _mock_engine([_fake_result([matched_row])])

    with patch("app.tools.db_query_tool_async.settings") as mock_settings:
        mock_settings.async_engine = engine
        results = await run_db_query_tool("비계 기록에서 확인해줘")

    assert conn.execute.call_count == 1
    assert results == [{"question": "비계 기록에서 확인해줘", "answer": "...", "created_at": "2026-07-16"}]
