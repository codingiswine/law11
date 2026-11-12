"""처벌 질문에 벌칙 조문을 코드로 찾아 넣는다 (#99).

실측(2026-11-12): "비계 설치 안전 기준 알려줘" 뒤 "그거 안 지키면 처벌은?"에 재난법 제78조의3
(안전조치명령 불이행 3년·3천만원)을 답했다. 정답은 산업안전보건법 제168조(제38조 위반 5년·5천만원).
제168조는 조문 번호 나열이라 벡터 15위 밖이고, #98의 타법 대체 금지 규칙으로도 2/2 그대로였다.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tools import law_rag_tool
from app.tools.law_rag_tool import LawSearch, cited_articles, penalty_articles, prior_cited_articles
from core.plan import ToolPlan


def test_cited_articles_parses_brackets_spaces_and_branch_numbers():
    txt = "- [산업안전보건기준에관한규칙 제70조] 제1항 … 산업안전보건법 제17조 제2항 … **산업안전보건법시행령 제16조**  … 재난 및 안전관리 기본법 제14조의2"
    assert cited_articles(txt) == [("산업안전보건기준에관한규칙", "70"), ("산업안전보건법", "17"),
                                   ("산업안전보건법시행령", "16"), ("재난및안전관리기본법", "14의2")]


def test_prior_cited_articles_reads_the_last_assistant_turn():
    ctx = ("사용자: 비계\nLaw11: [산업안전보건기준에관한규칙 제70조] …\n사용자: 그거\n"
           "Law11: 🔹 **결론**\n비계는…\n\n🔹 **법적 근거**\n- [산업안전보건법 제38조] 제1항: …")
    assert prior_cited_articles(ctx) == [("산업안전보건법", "38")], "여러 줄 답변의 인용은 첫 줄 뒤에 있다"
    assert prior_cited_articles("") == []


class _Conn:
    def __init__(self):
        self.calls = []

    async def execute(self, _sql, params):
        self.calls.append(params)
        if "art" in params:
            return SimpleNamespace(fetchone=lambda: ("산업안전보건기준에관한규칙", "1", "제1조(목적) 법 제37조부터 제40조까지 … 위임"))
        return SimpleNamespace(fetchall=lambda: [
            ("산업안전보건법", "167", "제167조(벌칙) 제38조…를 위반하여 근로자를 사망에 이르게 한 자는 7년 이하"),
            ("산업안전보건법", "168", "제168조(벌칙) 제38조제1항…을 위반한 자"),
        ])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


@pytest.mark.asyncio
async def test_rule_article_maps_to_base_law_penalties_with_delegation_evidence():
    conn = _Conn()
    with patch.object(law_rag_tool, "async_engine", SimpleNamespace(connect=lambda: conn)):
        out = await penalty_articles([("산업안전보건기준에관한규칙", "70")])
    assert [(a["law_name"], a["article_number"]) for a in out] == [
        ("산업안전보건기준에관한규칙", "1"), ("산업안전보건법", "168"), ("산업안전보건법", "167")], \
        "사망 특례(제167조)는 기본 벌칙(제168조) 뒤에 와야 한다"
    pen_params = next(p for p in conn.calls if "pat" in p)
    assert pen_params["law"] == "산업안전보건법" and "제(38|39)조" in pen_params["pat"]


async def _stream():
    for p in ["🔹 **결론**\n5년 이하\n\n🔹 **판단 근거**\n…"]:
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=p))])


@pytest.mark.asyncio
async def test_penalty_question_puts_looked_up_articles_first():
    found = LawSearch(source="qdrant", law_name=None, article_number="", is_direct_article=False,
                      articles=[{"law_name": "재난및안전관리기본법", "article_number": "78의3", "text": "안전조치명령", "score": 0.5}])
    pen = [{"law_name": "산업안전보건법", "article_number": "168", "text": "제168조(벌칙)", "score": 1.0}]
    captured = {}

    async def _create(**kw):
        captured["prompt"] = kw["messages"][-1]["content"]
        return _stream()

    ctx = "사용자: 비계 설치 안전 기준 알려줘\nLaw11: [산업안전보건기준에관한규칙 제70조] 제1항 …"
    with patch.object(law_rag_tool, "search_law_articles", AsyncMock(return_value=found)), \
         patch.object(law_rag_tool, "penalty_articles", AsyncMock(return_value=pen)) as lookup, \
         patch.object(law_rag_tool.settings, "openai_client",
                      SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))):
        chunks = [c async for c in law_rag_tool.run(ToolPlan(tool="law_rag_tool",
                  args={"query": "그거 안 지키면 처벌은 어떻게 돼?", "context": ctx}))]
    lookup.assert_awaited_once_with([("산업안전보건기준에관한규칙", "70")])
    assert captured["prompt"].index("제168조") < captured["prompt"].index("제78조의3"), "벌칙 조문이 맨 앞"
    src = next(c.payload for c in chunks if c.type == "source")
    assert src["retrieved_laws"][0]["article_number"] == "168"
    assert any("벌칙 조문 조회" in c.payload for c in chunks if c.type == "status")


@pytest.mark.asyncio
async def test_non_penalty_question_never_looks_up():
    found = LawSearch(source="qdrant", law_name=None, article_number="", is_direct_article=False,
                      articles=[{"law_name": "산업안전보건법", "article_number": "38", "text": "안전조치", "score": 0.6}])
    with patch.object(law_rag_tool, "search_law_articles", AsyncMock(return_value=found)), \
         patch.object(law_rag_tool, "penalty_articles", AsyncMock(return_value=[])) as lookup, \
         patch.object(law_rag_tool.settings, "openai_client",
                      SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=_stream()))))):
        [c async for c in law_rag_tool.run(ToolPlan(tool="law_rag_tool", args={"query": "안전조치 의무가 뭐야?", "context": ""}))]
    lookup.assert_not_awaited()
