"""시행 전 개정판이 현행처럼 저장·표시되던 문제 (#97).

실측(2026-11-12): 산업안전보건법 188개 조문 전부 enforcement_date = 2027-04-28. 법제처 DRF를
법령 ID로 호출하면 최신 공포본(2026-10-27 공포, 2027-04-28 시행)이 오고, efYd는 무시되며
연혁 API는 이 키로 HTML 오류를 돌려준다. 바뀐 조문은 18개(22122: 15, 21853: 4)지만 어느
조문이 바뀌었는지를 운영 코드가 알 수 없으므로, 날짜가 미래면 전부 알린다.
"""
from datetime import date

from app.tools.law_rag_tool import enforcement_notice
from app.tools.law_updater_async import pending_articles

_TODAY = date(2026, 11, 12)


def test_future_date_gets_a_pending_notice():
    n = enforcement_notice(date(2027, 4, 28), today=_TODAY)
    assert "시행 예정" in n and "다를 수 있습니다" in n


def test_past_or_missing_date_is_silent():
    assert enforcement_notice(date(2025, 9, 1), today=_TODAY) == ""
    assert enforcement_notice(_TODAY, today=_TODAY) == ""
    assert enforcement_notice(None, today=_TODAY) == ""
    assert enforcement_notice("2026-08-01", today=_TODAY) == ""
    assert "시행 예정" in enforcement_notice("2027-04-28", today=_TODAY)


def test_updater_lists_future_dated_articles():
    rows = [
        {"article_number_norm": "38", "enforcement_date": date(2027, 4, 28)},
        {"article_number_norm": "1", "enforcement_date": date(2025, 9, 1)},
        {"article_number_norm": "2", "enforcement_date": None},
    ]
    assert pending_articles(rows, today=_TODAY) == [("38", date(2027, 4, 28))]
