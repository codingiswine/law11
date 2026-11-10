"""rubric 채점의 집계 규칙과 유형 커버리지를 지킨다 (#80).

채점기 호출은 LLM이라 여기서 검증하지 않는다. 대신 **채점기가 이상한 응답을 줬을 때
집계가 조용히 틀리지 않는지**를 본다 — 항목을 빼먹거나 사전에 없는 판정을 돌려줄 때
그걸 0점으로 세면 "품질 하락"처럼 보이고, 1점으로 세면 결함을 숨긴다. 둘 다 틀렸고
정답은 평균에서 제외하는 것이다.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.eval_rubric import (
    GOLDEN_PATH, RUBRICS, SCORE, _load_types, citation_present, score_case,
)


@pytest.mark.parametrize("answer, expected", [
    # 실측(#80): 채점기는 공백이 든 법령명을 못 읽어 이 답변을 "조문 번호가 없다"며 깎았다
    ("산업안전보건기준에 관한 규칙 제32조는 보호구를 지급하도록 규정하고 있습니다.", "충족"),
    ("[산업안전보건법 제17조]에 따라 안전관리자를 둬야 합니다.", "충족"),
    ("중대재해처벌등에관한법률 제6조제1항에 따라 처벌됩니다.", "충족"),
    ("산업안전보건법 제14조의2는 …", "충족"),
    ("사업주는 필요한 조치를 해야 합니다.", "미충족"),
    ("산업안전보건법에 따라 조치해야 합니다.", "미충족"),       # 조문 번호 없음
])
def test_citation_is_checked_mechanically_not_by_the_judge(answer, expected):
    assert citation_present(answer)["verdict"] == expected


@pytest.mark.asyncio
async def test_mechanical_item_overrides_the_judge():
    """채점기가 `근거 조문`을 미충족이라고 해도 기계 판정이 기준이다 (#80 2차)."""
    reply = {"items": [{"name": it["name"], "verdict": "미충족", "reason": "r", "quote": ""}
                       for it in RUBRIC]}
    answer = "산업안전보건기준에 관한 규칙 제32조는 보호구 지급을 규정합니다."
    with patch("app.config.settings.openai_client", _judge_reply(reply)):
        res = await score_case("q", answer, CONTEXTS, RUBRIC)
    cite = [i for i in res["items"] if i["name"] == "근거 조문"][0]
    assert cite["verdict"] == "충족", "LLM 판정이 기계 판정을 덮어썼다"

RUBRIC = RUBRICS["penalty"]
CONTEXTS = ["제6조(처벌) 1 … 1년 이상의 징역 또는 10억원 이하의 벌금에 처한다."]
# `근거 조문` 항목은 기계 판정이므로, 답변에 인용이 있으면 LLM 응답과 무관하게 충족이다.
ANSWER = "중대재해처벌등에관한법률 제6조제1항에 따라 1년 이상의 징역에 처합니다."


def _judge_reply(payload):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=json.dumps(payload, ensure_ascii=False)))]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


def test_every_golden_question_type_has_a_rubric():
    # 유형을 추가하고 rubric을 빼먹으면 기본 rubric으로 조용히 채점되는 대신 터져야 한다.
    types = _load_types()
    assert set(types.values()) <= set(RUBRICS)
    assert len(types) == len(json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["dataset"])


def test_score_mapping_is_three_valued():
    assert SCORE == {"충족": 1.0, "부분충족": 0.5, "미충족": 0.0}


@pytest.mark.asyncio
async def test_all_items_satisfied_scores_one():
    reply = {"items": [{"name": it["name"], "verdict": "충족", "reason": "r", "quote": "q"}
                       for it in RUBRIC]}
    with patch("app.config.settings.openai_client", _judge_reply(reply)):
        res = await score_case("q", ANSWER, CONTEXTS, RUBRIC)
    assert res["score"] == 1.0
    assert [i["verdict"] for i in res["items"]] == ["충족"] * len(RUBRIC)


@pytest.mark.asyncio
async def test_missing_item_is_excluded_from_the_average_not_counted_as_zero():
    # 채점기가 3항목 중 1개만 판정했다. 나머지를 0으로 세면 0.33이 되어 품질
    # 하락으로 읽히고, 1로 세면 결함을 가린다 — 평균에서 빼야 한다.
    reply = {"items": [{"name": RUBRIC[0]["name"], "verdict": "충족", "reason": "r", "quote": "q"}]}
    with patch("app.config.settings.openai_client", _judge_reply(reply)):
        res = await score_case("q", ANSWER, CONTEXTS, RUBRIC)
    assert res["score"] == 1.0, "판정하지 않은 항목이 0점으로 집계됐다"
    # 3번째(근거 조문)는 기계 판정이라 채점기가 빠뜨려도 ERROR가 되지 않는다.
    assert [i["verdict"] for i in res["items"]] == ["충족", "ERROR", "충족"]


@pytest.mark.asyncio
async def test_not_applicable_is_excluded_not_counted_as_zero():
    """조문이 그 항목을 규정하지 않으면 채점이 성립하지 않는다 (#80 1차 실측 교훈).

    0점으로 세면 조문에 수치가 없는 질문이 '수치 기준 미충족'으로 평균을 끌어내린다 —
    실제로 GS-017·GS-018에서 그렇게 됐고 standard 유형 평균이 0.444로 찍혔다.
    """
    reply = {"items": [
        {"name": RUBRIC[0]["name"], "verdict": "충족", "reason": "r", "quote": "q"},
        {"name": RUBRIC[1]["name"], "verdict": "해당없음", "reason": "조문에 분기가 없다", "quote": ""},
        {"name": RUBRIC[2]["name"], "verdict": "충족", "reason": "r", "quote": "q"},
    ]}
    with patch("app.config.settings.openai_client", _judge_reply(reply)):
        res = await score_case("q", ANSWER, CONTEXTS, RUBRIC)
    assert res["score"] == 1.0, "해당없음이 0점으로 집계됐다"
    assert res["items"][1]["verdict"] == "해당없음", "해당없음이 ERROR로 버려졌다"


@pytest.mark.asyncio
async def test_unknown_verdict_and_invented_item_are_not_scored():
    reply = {"items": [
        {"name": RUBRIC[0]["name"], "verdict": "아주 좋음", "reason": "r", "quote": "q"},
        {"name": RUBRIC[1]["name"], "verdict": "미충족", "reason": "r", "quote": ""},
        {"name": "채점기가 지어낸 항목", "verdict": "충족", "reason": "r", "quote": "q"},
    ]}
    with patch("app.config.settings.openai_client", _judge_reply(reply)):
        res = await score_case("q", "a", CONTEXTS, RUBRIC)
    names = [i["name"] for i in res["items"]]
    assert "채점기가 지어낸 항목" not in names, "요청하지 않은 항목이 집계에 들어갔다"
    assert res["items"][0]["verdict"] == "ERROR"      # 사전에 없는 판정
    assert res["score"] == 0.0                         # 유효 판정은 미충족 1개뿐
