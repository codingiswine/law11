"""후속 질문의 검색어 보강 (#96).

실측(2026-11-12): "밀폐공간 … 산소농도 기준" 뒤에 "그럼 그 측정은 누가 해야 해?"를 물으면
답변은 이전 대화로 제619조의2를 인용했지만 **검색**은 현재 문장만 임베딩해 53·184·125·
284·189처럼 무관한 조문을 올렸다. 참고 법령 칩이 본문과 안 맞고, 맥락이 약하면 답도 뭉개진다.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tools import law_rag_tool
from app.tools.law_rag_tool import prior_user_question, search_law_articles

_CTX = "사용자: 밀폐공간 작업 전 적정 공기 산소농도 기준이 뭐야?\nLaw11: 🔹 **결론** 18퍼센트 이상…"


def test_follow_up_with_demonstrative_gets_prior_user_question():
    assert prior_user_question("그럼 그 측정은 누가 해야 해?", _CTX) == "밀폐공간 작업 전 적정 공기 산소농도 기준이 뭐야?"
    assert prior_user_question("그거 다시 말해줘", _CTX).startswith("밀폐공간")


def test_standalone_or_long_questions_are_left_alone():
    assert prior_user_question("안전관리자 선임 기준은?", _CTX) == ""
    assert prior_user_question("그럼 그 측정은 누가 해야 해?", "") == ""
    long_q = "그럼 " + "밀폐공간에서 작업할 때 산소 농도를 측정하는 사람의 자격 요건과 교육 의무는 " * 2
    assert prior_user_question(long_q, _CTX) == ""


@pytest.mark.asyncio
async def test_prior_question_is_added_to_the_embedding_only():
    """임베딩 입력에는 붙고, 법령명·조문번호 파싱은 현재 질문만 본다."""
    hit = SimpleNamespace(score=0.6, payload={"law_name": "산업안전보건기준에관한규칙", "article_number_norm": "619의2",
                                              "text": "본문", "enforcement_date": "2024-01-01"})
    embed = AsyncMock(return_value=[0.0] * 1536)
    with patch.multiple(law_rag_tool, get_embedding_async=embed,
                        qdrant=SimpleNamespace(search=AsyncMock(return_value=[hit]))):
        found = await search_law_articles("그럼 그 측정은 누가 해야 해?",
                                          prior_question="산업안전보건법 제38조 내용 알려줘")
    sent = embed.await_args.args[0]
    assert sent.startswith("산업안전보건법 제38조 내용 알려줘 그럼 그 측정은")
    assert found.law_name is None and found.article_number == "", "앞 턴의 법령명·조문번호가 파싱에 새면 안 된다"
    assert found.source == "qdrant"


def test_run_passes_prior_question_into_search():
    import inspect
    assert "search_law_articles(query, prior_user_question(query, context))" in inspect.getsource(law_rag_tool.run)
