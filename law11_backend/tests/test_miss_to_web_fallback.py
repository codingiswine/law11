"""모델이 "제공된 조문에서 확인되지 않음"을 인정하면 거기서 멈추지 않고 웹으로 보완한다 (#98).

실측(2026-11-12): "중대재해처벌법은 몇 명 이상 사업장부터 적용돼?"에 조문 5개가 왔지만 정답
(제3조, 벡터 15위 밖)이 없어 "확인되지 않습니다"로 끝났다. 빈손 검색은 웹으로 가는데
이 경우는 안 갔다 — 사용자 입장에서 둘은 같은 "모름"이다.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools import law_rag_tool
from app.tools.law_rag_tool import LawSearch, conclusion_admits_miss
from core.plan import ToolPlan

_FOUND = LawSearch(source="qdrant", law_name=None, article_number="", is_direct_article=False,
                   articles=[{"law_name": "중대재해처벌등에관한법률", "article_number": "7", "text": "본문", "score": 0.57}])


class _Stream:
    def __init__(self, pieces):
        self._pieces = pieces
        self.closed = False

    def __aiter__(self):
        async def gen():
            for p in self._pieces:
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=p))])
        return gen()

    async def close(self):
        self.closed = True


async def _web_stub(*_a, **_kw):
    yield law_rag_tool.ToolChunk(type="text", payload="[웹 답변]")


async def _collect(pieces, web_mock):
    stream = _Stream(pieces)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=stream))))
    with patch.object(law_rag_tool, "search_law_articles", AsyncMock(return_value=_FOUND)), \
         patch.object(law_rag_tool.settings, "openai_client", client), \
         patch.object(law_rag_tool, "_answer_from_web", web_mock):
        chunks = [c async for c in law_rag_tool.run(ToolPlan(tool="law_rag_tool", args={"query": "중대재해처벌법은 몇 명부터 적용돼?"}))]
    return chunks, stream


def test_conclusion_miss_detection_only_looks_before_the_basis_section():
    assert conclusion_admits_miss("🔹 **결론**\n제공된 조문에서는 확인되지 않습니다.\n\n🔹 **판단 근거**\n…")
    assert not conclusion_admits_miss("🔹 **결론**\n5명 미만은 제외됩니다.\n\n🔹 **판단 근거**\n별표는 확인되지 않습니다")


@pytest.mark.asyncio
async def test_admitted_miss_is_discarded_and_web_fallback_runs():
    web = MagicMock(side_effect=_web_stub)
    pieces = ["🔹 **결론**\n", "제공된 조문에서는 ", "확인되지 않습니다.\n\n", "🔹 **판단 근거**\n", "조문에 인원 기준이 없습니다."]
    chunks, stream = await _collect(pieces, web)
    texts = "".join(c.payload for c in chunks if c.type == "text")
    assert "확인되지 않습니다" not in texts, "미확인 결론이 사용자에게 나가면 안 된다"
    assert "[웹 답변]" in texts
    assert any("Web 검색으로 보완" in c.payload for c in chunks if c.type == "status")
    assert web.call_args.kwargs.get("notice") == law_rag_tool.WEB_MISS_NOTICE
    assert not [c for c in chunks if c.type == "meta"], "버린 답의 meta가 로그로 가면 안 된다"
    assert stream.closed


@pytest.mark.asyncio
async def test_confident_answer_streams_through_untouched():
    web = MagicMock(side_effect=_web_stub)
    pieces = ["🔹 **결론**\n", "상시 근로자 5명 미만 사업장은 제외됩니다.\n\n", "🔹 **판단 근거**\n", "제3조에 따릅니다."]
    chunks, _ = await _collect(pieces, web)
    texts = "".join(c.payload for c in chunks if c.type == "text")
    assert texts.startswith("".join(pieces))
    web.assert_not_called()
    assert [c for c in chunks if c.type == "meta"]


def test_answer_prompt_forbids_substituting_other_laws():
    import inspect
    src = inspect.getsource(law_rag_tool.run)
    assert "다른 법령·다른 대상의 조문이나 수치로" in src and "해당하는 분기만 결론에 쓴다" in src
