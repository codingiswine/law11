"""별표 수집·검색 (#104).

조문은 "별표 3과 같다"로 끝나고 숫자는 별표에 있다. 별표가 DB에 없어서 그런 질문이
"미확인 → 웹"으로 샜다(#98·#101). 여기서 고정하는 것:
  · 줄 그림 표 → 텍스트 변환과 최상위 행 경계 분할 (표 머리 반복)
  · 별표 key 스킴이 수집(annex_norm)과 조회(normalize_article·article_display)에서 같다 — #28 재발 방지
  · 검색된 조문이 가리키는 별표를 근거에 붙인다
  · 평가에서 별표는 "(제N조 관련)" 조문으로 채점한다
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools import law_rag_tool
from app.tools.law_rag_tool import article_display, bound_annex_number, normalize_article
from app.tools.law_updater_async import annex_norm, extract_annex_payloads, split_annex
from eval.eval_retrieval import _label

TABLE = """■ 산업안전보건법 시행규칙 [별표 4]
  안전보건교육 교육과정별 교육시간(제26조제1항 등 관련)
┌────────┬───────────┐
│교육과정        │교육시간            │
├────────┼───────────┤
│가. 정기교육    │매반기 6시간 이상   │
│                ├───────────┤
│                │매반기 12시간 이상  │
├────────┼───────────┤
│나. 채용 시 교  │8시간 이상          │
│육              │                    │
└────────┴───────────┘"""


def test_split_annex_keeps_rows_and_repeats_header():
    chunks = split_annex(TABLE, limit=40)   # 한도는 표 머리를 뺀 본문 기준
    assert len(chunks) == 2
    for c in chunks:
        assert "교육과정 | 교육시간" in c          # 표 머리가 청크마다 반복된다
        assert "┌" not in c and "├" not in c       # 테두리 제거
    assert "가. 정기교육 | 매반기 6시간 이상" in chunks[0]
    assert "매반기 12시간 이상" in chunks[0]          # 중첩 칸 경계(행 중간 ├)에서는 자르지 않는다
    assert "나. 채용 시 교 | 8시간 이상" in chunks[1]


def test_split_annex_plain_text_annex():
    chunks = split_annex("■ 별표 2\n1. 첫째 항목\n2. 둘째 항목")
    assert chunks == ["■ 별표 2\n1. 첫째 항목\n2. 둘째 항목"]


@pytest.mark.parametrize("number,branch,norm,display", [
    ("0003", "00", "별표3", "별표 3"),
    ("0021", "02", "별표21의2", "별표 21의2"),
])
def test_annex_key_scheme_matches_on_both_sides(number, branch, norm, display):
    assert annex_norm(number, branch) == norm
    assert normalize_article(norm) == norm
    assert normalize_article(f"{norm}#2") == f"{norm}#2"
    assert normalize_article(display) == norm
    assert article_display(f"{norm}#2") == display
    assert normalize_article("제14조의2") == "14의2"   # 기존 조문 스킴은 그대로


def test_extract_annex_payloads_skips_forms_and_deleted():
    drf = {"법령": {"별표": {"별표단위": [
        {"별표구분": "별표", "별표번호": "0004", "별표가지번호": "00",
         "별표제목": "안전보건교육 교육과정별 교육시간(제26조제1항 등 관련)", "별표내용": [[TABLE]]},
        {"별표구분": "별표", "별표번호": "0010", "별표가지번호": "00", "별표제목": "삭제 <2023. 11. 14.>",
         "별표내용": [["삭제"]]},
        {"별표구분": "서식", "별표번호": "0001", "별표가지번호": "00", "별표제목": "신청서", "별표내용": [["서식"]]},
    ]}}}
    rows = extract_annex_payloads("산업안전보건법시행규칙", drf)
    assert {r["annex"] for r in rows} == {"별표4"}
    assert rows[0]["article_number_norm"] == "별표4#1"
    assert rows[0]["related_article"] == "26"
    assert rows[0]["text"].startswith("[산업안전보건법시행규칙 별표 4]")


def test_bound_annex_number():
    assert bound_annex_number("「산업안전보건법」 시행령[별표 1] 제5호다목에 따라", "산업안전보건법시행령") == "별표1"
    assert bound_annex_number("산업안전보건법 시행령에서 안전관리자 선임 기준", "산업안전보건법시행령") == ""


def test_eval_label_maps_annex_to_related_article():
    assert _label("산업안전보건법시행령", "별표3#1", "16") == "산업안전보건법시행령 제16조"
    assert _label("산업안전보건법시행령", "16") == "산업안전보건법시행령 제16조"
    assert _label("산업안전보건법시행령", "별표9#1", "") == "산업안전보건법시행령 별표9#1"


@pytest.mark.asyncio
async def test_attach_annex_referenced_by_found_article():
    found = SimpleNamespace(articles=[{"law_name": "산업안전보건법시행령", "article_number": "16",
                                       "text": "① 안전관리자의 수 및 선임방법은 별표 3과 같다.", "score": 0.7}])
    captured = {}

    async def _search(*_a, query_filter=None, **_kw):
        captured["annex"] = query_filter.must[1].match.value
        return [SimpleNamespace(score=0.5, payload={"law_name": "산업안전보건법시행령",
                                                    "article_number_norm": "별표3#1", "text": "별표 3 본문",
                                                    "related_article": "16"})]

    with patch.object(law_rag_tool, "qdrant", SimpleNamespace(search=_search)):
        await law_rag_tool._attach_annexes(found, [0.0])
    assert captured["annex"] == "별표3"
    assert found.articles[-1]["article_number"] == "별표3#1"
    assert found.articles[-1]["attached"] is True


def test_embedding_input_is_cut_only_when_over_the_token_limit():
    """건축법 시행령 제119조(8,435토큰)가 임베딩 한도를 넘어 동기화가 400으로 실패했다 (#106).
    한도 안의 텍스트는 그대로 둔다 — 기존 조문 벡터가 바뀌지 않아야 한다."""
    from app.tools.law_updater_async import EMBED_MAX_TOKENS, _fit_embedding_input
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    short = "제1조(목적) 이 법은 안전을 목적으로 한다."
    assert _fit_embedding_input(short) == short
    long = "가나다라 " * 5000
    assert len(enc.encode(_fit_embedding_input(long))) <= EMBED_MAX_TOKENS
