"""search_law_articles 계층 판단 회귀 테스트.

운영(law_rag_tool.run)과 평가(eval/retriever)가 검색 우선순위를 각자 구현하던
시절, 30개 골든셋 중 3건에서 서로 다른 조문으로 돌았다 (실측 2026-10-27).
여기서 고정하는 건 그때 갈라졌던 판단들이다 — threshold 게이트와 경로 선택.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools import law_rag_tool
from app.tools.law_rag_tool import parse_article_number, search_law_articles


def _hit(law, article, score, text="조문 본문"):
    return SimpleNamespace(score=score, payload={
        "law_name": law, "article_number_norm": article,
        "text": text, "enforcement_date": "2024-01-01",
    })


class _FakeConn:
    def __init__(self, row):
        self._row = row

    async def execute(self, *_a, **_kw):
        return SimpleNamespace(fetchone=lambda: self._row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def _fake_engine(row):
    return SimpleNamespace(connect=lambda: _FakeConn(row))


def _patch(qdrant_hits, pg_row=None):
    """qdrant.search가 호출될 때마다 qdrant_hits를 순서대로 돌려준다."""
    calls = list(qdrant_hits)

    async def _search(*_a, **_kw):
        return calls.pop(0) if calls else []

    return patch.multiple(
        law_rag_tool,
        qdrant=SimpleNamespace(search=_search, scroll=AsyncMock(return_value=([], None))),
        async_engine=_fake_engine(pg_row),
        get_embedding_async=AsyncMock(return_value=[0.0] * 1536),
    )


# ── 조문 번호 파싱 ─────────────────────────────────────────

@pytest.mark.parametrize("q,expected", [
    ("산업안전보건법 제17조의 내용은?", "17"),
    ("산업안전보건법 제14조의2 알려줘", "14의2"),
    ("안전관리자 선임 기준은?", ""),
])
def test_parse_article_number(q, expected):
    assert parse_article_number(q) == expected


# ── 계층 판단 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_direct_article_hits_postgres():
    """법령명 + 조문번호 → PG 정확 매칭"""
    with _patch([], pg_row=("제17조 본문", "2024-01-01")):
        found = await search_law_articles("산업안전보건법 제17조의 내용은?")
    assert found.source == "pg"
    assert found.is_direct_article is True
    assert found.articles[0]["text"] == "제17조 본문"


@pytest.mark.asyncio
async def test_direct_article_miss_does_not_substitute_another_article():
    """PG miss는 '그 조문 없음'이다 — Qdrant로 다른 조문을 대신 꺼내면 안 된다."""
    with _patch([[_hit("산업안전보건법", "38", 0.99)]], pg_row=None):
        found = await search_law_articles("산업안전보건법 제9999조 내용은?")
    assert found.source == "missing"
    assert found.articles == []


@pytest.mark.asyncio
async def test_no_law_name_below_threshold_falls_back_to_web():
    """법령명 미인식 + 최고점 < 0.45 → 웹 폴백.

    회귀: 평가 경로에 이 게이트가 없어서 0.3548짜리 결과를 RAGAS 근거로
    쓰고 있었다 (GS-013 거푸집 동바리, GS-027 재난사태 선포).
    """
    with _patch([[_hit("산업안전보건기준에관한규칙", "330", 0.3548)]] * 2):
        found = await search_law_articles("거푸집 동바리 설치 기준은 어떻게 되나요?")
    assert found.source == "web"
    assert found.articles == []


@pytest.mark.asyncio
async def test_no_law_name_above_threshold_returns_deduped_articles():
    """법령명 미인식 + 0.45 이상 → 상위 조문들, 같은 조문은 한 번만."""
    hits = [
        _hit("산업안전보건법", "17", 0.80),
        _hit("산업안전보건법", "17", 0.78),   # 같은 조문 중복 청크
        _hit("산업안전보건법", "15", 0.70),
    ]
    with _patch([hits]):
        found = await search_law_articles("안전관리자 선임 기준은 무엇인가요?")
    assert found.source == "qdrant"
    assert [(a["law_name"], a["article_number"]) for a in found.articles] == [
        ("산업안전보건법", "17"), ("산업안전보건법", "15"),
    ]


@pytest.mark.asyncio
async def test_law_name_only_uses_stricter_threshold_and_single_article():
    """법령명만 인식 → 해당 법령 안에서만 검색, threshold 0.5, 최상위 1건.

    회귀: 평가 경로에 이 경로가 없어서 priority 필터 + 0.45로 5건을
    넘기고 있었다 (GS-026 '재난'의 정의 — 운영은 1건).
    """
    hits = [_hit("재난및안전관리기본법", "3", 0.5907), _hit("재난및안전관리기본법", "2", 0.55)]
    with _patch([hits]):
        found = await search_law_articles("재난및안전관리기본법에서 '재난'의 정의는?")
    assert found.source == "qdrant"
    assert len(found.articles) == 1
    assert found.articles[0]["article_number"] == "3"


@pytest.mark.asyncio
async def test_law_name_only_below_stricter_threshold_falls_back_to_web():
    """0.45는 넘지만 0.5 미만 → 범위를 좁혔는데도 미달이므로 웹 폴백."""
    with _patch([[_hit("재난및안전관리기본법", "3", 0.48)]]):
        found = await search_law_articles("재난및안전관리기본법에서 '재난'의 정의는?")
    assert found.source == "web"


@pytest.mark.asyncio
async def test_unknown_law_with_article_number_skips_vector_results():
    """DB에 없는 법 + 조문번호 → threshold를 넘겨도 신뢰하지 않고 웹 폴백 (README #31)."""
    with _patch([[_hit("재난및안전관리기본법", "3", 0.92)]] * 2):
        found = await search_law_articles("소방기본법 2조 알려줘")
    assert found.source == "web"


# ── 평가 경로가 같은 함수를 쓰는가 ──────────────────────────

def test_eval_retriever_reuses_the_shared_search():
    """eval/retriever.py가 자체 검색을 다시 구현하면 이 테스트가 깨진다."""
    src = (Path(__file__).parent.parent / "eval" / "retriever.py").read_text(encoding="utf-8")
    assert "search_law_articles" in src
    for own_search in ("search_qdrant_async", "qdrant.search", "FROM law_chunks"):
        assert own_search not in src, f"eval/retriever.py가 검색을 다시 구현하고 있음: {own_search}"
