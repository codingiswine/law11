"""DB 조회 실패가 'Citation 누락 0건'으로 보고되지 않는지 지킨다 (#78).

`verify_citations`가 예외를 삼키고 missing을 비워 두면, PG가 꺼진 상태에서
"Citation 누락 0건"이 출력되고 그 숫자가 README로 올라간다. 측정하지 않은 것과
통과한 것은 다른 결과다 — #31에서 PG 장애를 "조문이 없다"고 사용자에게 오보한
것과 같은 모양이다.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from eval.eval_hallucination import extract_cited_articles, verify_citations

ANSWER = "[산업안전보건법 제17조]에 따라 안전관리자를 둬야 합니다."


def _engine(*, rows=None, error=None):
    conn = AsyncMock()
    if error:
        conn.execute.side_effect = error
    else:
        conn.execute.return_value = MagicMock(fetchone=MagicMock(return_value=rows))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine = MagicMock()
    engine.connect.return_value = ctx
    return engine


@pytest.mark.asyncio
async def test_db_error_is_unverified_not_ok():
    with patch("app.config.settings.async_engine", _engine(error=OSError("connect failed"))):
        result = await verify_citations(ANSWER)

    assert result["verdict"] == "UNVERIFIED", "DB 장애가 OK로 보고되면 거짓 0건이 된다"
    assert result["errors"] and "OSError" in result["errors"][0]


@pytest.mark.asyncio
async def test_existing_article_is_ok():
    with patch("app.config.settings.async_engine", _engine(rows=(1,))):
        result = await verify_citations(ANSWER)

    assert result["verdict"] == "OK" and result["errors"] == []


@pytest.mark.asyncio
async def test_absent_article_is_citation_miss():
    with patch("app.config.settings.async_engine", _engine(rows=None)):
        result = await verify_citations(ANSWER)

    assert result["verdict"] == "CITATION_MISS"
    assert result["missing"] == ["산업안전보건법 제17조"]


def test_answer_without_citation_needs_no_db():
    assert extract_cited_articles("조문 인용이 없는 답변입니다.") == []
