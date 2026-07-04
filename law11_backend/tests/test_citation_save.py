import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.routes import save_citations


@pytest.mark.asyncio
async def test_save_citations_inserts_rows():
    citations = [
        {"law_name": "산업안전보건법", "article_number": "17", "score": 0.75, "rank": 1},
        {"law_name": "산업안전보건법", "article_number": "18", "score": 0.60, "rank": 2},
    ]
    mock_conn = AsyncMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.routes.async_engine") as mock_engine:
        mock_engine.begin.return_value = mock_ctx
        await save_citations(assistant_id=42, citations=citations)

    assert mock_conn.execute.call_count == 2


@pytest.mark.asyncio
async def test_save_citations_empty_list_does_nothing():
    with patch("app.api.routes.async_engine") as mock_engine:
        await save_citations(assistant_id=42, citations=[])

    mock_engine.begin.assert_not_called()


@pytest.mark.asyncio
async def test_save_citations_db_error_does_not_raise():
    citations = [{"law_name": "테스트법", "article_number": "1", "score": 0.9, "rank": 1}]
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = Exception("DB 연결 실패")
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.routes.async_engine") as mock_engine:
        mock_engine.begin.return_value = mock_ctx
        await save_citations(assistant_id=1, citations=citations)
