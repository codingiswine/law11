from datetime import date

from app.tools import case_law_rag_tool
from app.tools import case_law_updater_async as updater


def test_detect_case_number_supreme_court_format():
    assert case_law_rag_tool.detect_case_number("대법원 2024도5902 판결 내용 알려줘") == "2024도5902"


def test_detect_case_number_with_spaces():
    """실사용에서 "2024 도 5902"처럼 띄어 쓸 수 있음 — 정규식이 공백을 허용하고
    반환값에서는 제거해야 한다."""
    assert case_law_rag_tool.detect_case_number("2024 도 5902 판례 요지가 뭐야?") == "2024도5902"


def test_detect_case_number_none_when_absent():
    assert case_law_rag_tool.detect_case_number("산업안전보건법 관련 대법원 판례 있어?") is None


def test_normalize_case_number_strips_whitespace():
    """사건번호는 조문과 달리 가지번호 스킴이 없다 — 공백/전각만 제거."""
    assert case_law_rag_tool.normalize_case_number("2024 도 5902") == "2024도5902"
    assert case_law_rag_tool.normalize_case_number("2024도5902") == "2024도5902"


def test_strip_html_removes_tags():
    """DRF 판례 상세조회 응답의 판시사항/판결요지 필드에 <br/> 등 HTML 태그가
    섞여 나오는 것을 실측 확인 (law.go.kr target=prec 스파이크 검증)."""
    assert updater.strip_html("<br/> [1] 산업안전보건법상...") == "[1] 산업안전보건법상..."
    assert updater.strip_html(None) == ""
    assert updater.strip_html("") == ""


def test_parse_judgment_date_from_compact_format():
    """상세조회 응답은 'YYYYMMDD' 형태 (실측 확인)."""
    assert updater.parse_judgment_date("20260625") == date(2026, 6, 25)


def test_parse_judgment_date_from_dotted_format():
    """검색결과 응답은 'YYYY.MM.DD' 형태 (실측 확인)."""
    assert updater.parse_judgment_date("2026.06.25") == date(2026, 6, 25)


def test_parse_judgment_date_invalid_returns_none():
    assert updater.parse_judgment_date("") is None
    assert updater.parse_judgment_date(None) is None
    assert updater.parse_judgment_date("불명") is None
