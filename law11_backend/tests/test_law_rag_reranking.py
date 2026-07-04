import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.plan import ToolPlan
from app.tools import law_rag_tool


def _make_hits(n: int):
    return [
        MagicMock(
            score=0.8,
            payload={
                "text": f"조문내용{i}",
                "law_name": "산업안전보건법",
                "article_number_norm": str(i),
            },
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_no_law_name_path_calls_reranker_with_10_docs():
    """법령명 미인식 경로: Qdrant limit=10 후 reranker 호출 확인"""
    hits = _make_hits(10)

    class _FakeStream:
        def __aiter__(self): return self
        async def __anext__(self): raise StopAsyncIteration

    plan = ToolPlan(tool="law_rag_tool", args={"query": "위험물 보관 기준이 뭐야"})

    with patch("app.tools.law_rag_tool.get_embedding_async", new_callable=AsyncMock, return_value=[0.1] * 3072), \
         patch("app.tools.law_rag_tool.reranker") as mock_reranker, \
         patch("app.tools.law_rag_tool.qdrant") as mock_qdrant, \
         patch("app.tools.law_rag_tool.settings") as mock_settings:

        mock_qdrant.search = AsyncMock(return_value=hits)
        mock_reranker.rerank.return_value = [2, 5, 1, 8, 3]
        mock_settings.openai_client.chat.completions.create = AsyncMock(
            return_value=_FakeStream()
        )

        chunks = []
        async for chunk in law_rag_tool.run(plan):
            chunks.append(chunk)

    mock_reranker.rerank.assert_called_once()
    call_args = mock_reranker.rerank.call_args
    assert len(call_args[0][1]) == 10       # 10개 문서 전달 (positional arg)
    assert call_args[1].get("top_k") == 5  # top_k=5 (keyword arg)


@pytest.mark.asyncio
async def test_no_law_name_path_uses_reranked_order():
    """reranker가 반환한 인덱스 순서로 컨텍스트가 구성되는지 확인"""
    hits = _make_hits(10)

    captured_prompt = []

    async def _capture_stream(*args, **kwargs):
        msgs = kwargs.get("messages") or (args[0] if args else [])
        if msgs:
            captured_prompt.append(str(msgs))

        class _Stream:
            def __aiter__(self): return self
            async def __anext__(self): raise StopAsyncIteration
        return _Stream()

    plan = ToolPlan(tool="law_rag_tool", args={"query": "위험물 보관 기준"})

    with patch("app.tools.law_rag_tool.get_embedding_async", new_callable=AsyncMock, return_value=[0.1] * 3072), \
         patch("app.tools.law_rag_tool.reranker") as mock_reranker, \
         patch("app.tools.law_rag_tool.qdrant") as mock_qdrant, \
         patch("app.tools.law_rag_tool.settings") as mock_settings:

        mock_qdrant.search = AsyncMock(return_value=hits)
        mock_reranker.rerank.return_value = [2, 0, 1, 3, 4]
        mock_settings.openai_client.chat.completions.create = _capture_stream

        async for _ in law_rag_tool.run(plan):
            pass

    # 재정렬 인덱스 2가 첫 번째로 와야 함
    assert any("조문내용2" in p for p in captured_prompt)
