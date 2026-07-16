from app.tools.db_query_tool_async import _extract_search_term


def test_extract_search_term_strips_trigger_and_request_verb():
    """"비계 기록에서 확인해줘" → "비계"만 남아야 함
    (회귀 테스트: 트리거 키워드만 지우면 "확인해줘"가 남아 과거 메시지와
    전체 문자열 매치가 실패하던 버그)"""
    assert _extract_search_term("비계 기록에서 확인해줘") == "비계"


def test_extract_search_term_strips_db_keyword_only():
    assert _extract_search_term("안전관리자 선임 기준 데이터에서 찾아줘") == "안전관리자 선임 기준"


def test_extract_search_term_no_trigger_words_unchanged():
    assert _extract_search_term("비계") == "비계"
