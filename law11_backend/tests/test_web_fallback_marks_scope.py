"""웹 폴백 답변이 (a) 범위 밖임을 본문에 표시하고 (b) 조문 원문을 따옴표로 지어내지 않게 한다 (#94).

실측(2026-11-12): "근로기준법상 1년 근무하면 연차휴가는 며칠이야?"는 수록 범위 밖이라
웹 경로로 갔는데, 답변이 [법적 근거]에 근로기준법 제60조 제1항을 따옴표로 "인용"했다.
따옴표 안 문장은 조문 원문이 아니었다(80% 출근 요건이 빠짐). 화면에는 웹 결과라는
표시가 없어 DB 조문 답변과 구분되지 않았다. 3회 모두 같은 형태.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.tools import law_rag_tool as mod

_WEB = {"summaries": "근로기준법 제60조 연차휴가 요약", "raw_results": [{"title": "t", "snippet": "s", "link": "http://x"}]}


async def _collect(captured):
    async def _create(**kw):
        captured["messages"] = kw["messages"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="🔹 **결론** 모델 답변"))])

    chunks = []
    with patch.object(mod, "summarize_web", AsyncMock(return_value=_WEB)), \
         patch.object(mod.settings, "openai_client",
                      SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))):
        async for c in mod._answer_from_web("근로기준법상 연차휴가는 며칠이야?", "", False):
            chunks.append(c)
    return chunks


@pytest.mark.asyncio
async def test_web_answer_starts_with_out_of_scope_notice():
    chunks = await _collect({})
    texts = [c.payload for c in chunks if c.type == "text"]
    assert texts and texts[0] == mod.WEB_SCOPE_NOTICE, "웹 답변 첫 텍스트가 범위 밖 안내가 아니다"
    assert "범위 밖" in texts[0] and "웹 검색" in texts[0]
    assert "모델 답변" in texts[1], "안내 다음에 모델 답변이 와야 한다"


@pytest.mark.asyncio
async def test_web_prompt_forbids_quoting_statute_text():
    captured = {}
    await _collect(captured)
    system = next(m["content"] for m in captured["messages"] if m["role"] == "system")
    user = next(m["content"] for m in captured["messages"] if m["role"] == "user")
    assert "따옴표로 직접 인용하는 것 금지" in system
    assert "따옴표로 인용하지 마" in user
    assert "(웹 검색 기준, 원문 확인 필요)" in user
    assert "반드시 구체적인 조문 번호(제X조 제X항)를 인용" not in user, "'반드시 인용' 지시가 남아 있다"
