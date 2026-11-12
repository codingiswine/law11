"""인용(citation)·출처 URL은 검색이 실제로 찾은 조문에서 나와야 한다 (#82).

③ 경로(법령명만 인식 → 법령 필터 의미 검색)에서는 질문에 조문번호가 없어
found.article_number == "" 인데, run()이 그 값으로 인용을 만들어 citations에 빈
조문·URL에 "제조"가 들어갔다. 여기서는 run()에 ③ 결과를 주입해 meta/source 청크가
best(검색 결과)의 조문을 쓰는지 본다.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tools import law_rag_tool
from app.tools.law_rag_tool import LawSearch
from core.plan import ToolPlan


def _found_branch3():
    """법령명 인식 · 조문번호 미인식 · Qdrant 법령 필터 검색이 제17조를 찾은 결과."""
    return LawSearch(
        source="qdrant",
        law_name="산업안전보건법",
        article_number="",          # 질문에 조문번호가 없었다
        is_direct_article=False,
        articles=[{"law_name": "산업안전보건법", "article_number": "17",
                   "text": "사업주는 안전관리자를 두어야 한다.", "score": 0.81}],
    )


async def _stream():
    yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="요약"))])


def _fake_openai():
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=_stream()))))


async def _collect(found):
    with patch.object(law_rag_tool, "search_law_articles", AsyncMock(return_value=found)), \
         patch.object(law_rag_tool.settings, "openai_client", _fake_openai()):
        return [c async for c in law_rag_tool.run(ToolPlan(tool="law_rag_tool", args={"query": "산업안전보건법 안전관리자 선임 의무"}))]


@pytest.mark.asyncio
async def test_citation_uses_the_article_the_search_found_not_the_query():
    chunks = await _collect(_found_branch3())

    meta = next(c.payload for c in chunks if c.type == "meta")
    assert meta["citations"] == [{"law_name": "산업안전보건법", "article_number": "17", "score": 1.0, "rank": 1}], \
        "질문에 없던 조문번호는 검색 결과(best)에서 와야 한다"

    source = next(c.payload for c in chunks if c.type == "source")
    assert source["law_url"].endswith("/제17조")
    assert "제조" not in source["law_url"], "article_display('')가 만든 빈 조문 URL"
    assert source["retrieved_laws"] == meta["citations"]
