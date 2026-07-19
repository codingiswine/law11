from app.tools import law_rag_tool


def test_extract_web_citations_bracket_format():
    answer = "🔹 **법적 근거**\n- [소방기본법] 제2조: 이 법에서..."
    cites = law_rag_tool._extract_web_citations(answer)
    assert cites == [{"law_name": "소방기본법", "article_number": "2", "score": None, "rank": 1}]


def test_extract_web_citations_bold_markdown_format():
    """회귀 테스트: GPT가 대괄호 대신 볼드로 답할 때도 인용을 추출해야 함
    (실측: "산업안전보건법이랑 중대재해처벌법 비교" 질문에서 답변 본문은
    구체적 조문을 인용했는데 대괄호 전용 정규식이 매치 안 돼 출처 배지가
    하나도 안 뜸)"""
    answer = (
        "🔹 **법적 근거**\n"
        "- **산업안전보건법** 제66조 제1항: 사업주는...\n"
        "- **중대재해처벌법** 제2조 제1항: 중대재해란...\n"
    )
    cites = law_rag_tool._extract_web_citations(answer)
    assert cites == [
        {"law_name": "산업안전보건법", "article_number": "66", "score": None, "rank": 1},
        {"law_name": "중대재해처벌법", "article_number": "2", "score": None, "rank": 2},
    ]


def test_extract_web_citations_article_inside_bracket():
    """회귀 테스트: 조문 번호까지 대괄호 안에 넣는 변형도 추출해야 함
    (실측: "한 층에 소화기 몇 개?" 답변이 "[소방시설 설치 및 관리에 관한
    법률 제8조]" 형태로 인용해 배지가 하나도 안 뜸 — #34)"""
    answer = "🔹 **법적 근거**\n\n[소방시설 설치 및 관리에 관한 법률 제8조]\n소화기는 각 층에 설치해야 한다."
    cites = law_rag_tool._extract_web_citations(answer)
    assert cites == [{"law_name": "소방시설 설치 및 관리에 관한 법률", "article_number": "8", "score": None, "rank": 1}]


def test_extract_web_citations_mixed_formats_ranked_by_position():
    """세 표기 변형이 섞여도 등장 순서대로 rank가 매겨져야 함"""
    answer = (
        "[소방기본법] 제2조: 정의...\n"
        "[소방시설 설치 및 관리에 관한 법률 제8조] 소화기 설치...\n"
        "**산업안전보건법** 제38조: 안전조치...\n"
    )
    cites = law_rag_tool._extract_web_citations(answer)
    assert [(c["law_name"], c["article_number"], c["rank"]) for c in cites] == [
        ("소방기본법", "2", 1),
        ("소방시설 설치 및 관리에 관한 법률", "8", 2),
        ("산업안전보건법", "38", 3),
    ]


def test_mentions_unknown_law_true_for_unknown_law_plus_article():
    """DB에 없는 법 + 조문 번호 → True (예: 소방기본법)"""
    assert law_rag_tool.mentions_unknown_law("소방기본법 2조", None, "2") is True


def test_mentions_unknown_law_false_when_law_name_known():
    """9개 법 중 하나로 인식됐으면(law_name 있음) → False (정상 경로 유지)"""
    assert law_rag_tool.mentions_unknown_law("산업안전보건법 17조", "산업안전보건법", "17") is False


def test_mentions_unknown_law_false_without_article_number():
    """조문 번호 없는 일반 개념 질문 → False (예: '관련법 뭐있어?')"""
    assert law_rag_tool.mentions_unknown_law("관련법 뭐있어?", None, "") is False


def test_normalize_article_preserves_branch_number():
    """가지조문 보존 회귀 테스트: 예전엔 숫자만 추출해 "제14조의2"→"142"로
    제142조와 오매칭됐음 (v1.6.0 수정)"""
    assert law_rag_tool.normalize_article("제14조의2") == "14의2"
    assert law_rag_tool.normalize_article("14조의2") == "14의2"
    assert law_rag_tool.normalize_article("25의4") == "25의4"


def test_normalize_article_plain_number():
    assert law_rag_tool.normalize_article("제17조") == "17"
    assert law_rag_tool.normalize_article("17") == "17"
    assert law_rag_tool.normalize_article("") == ""


def test_article_display():
    assert law_rag_tool.article_display("14의2") == "제14조의2"
    assert law_rag_tool.article_display("17") == "제17조"


def test_expand_legal_terms_maps_statutory_term():
    """용어 매핑 회귀 테스트: "폭발 위험 분위기"는 규칙 공식 용어 "폭발위험장소"와
    어긋나 발파 조문이 검색되던 케이스 (실측 제230조 4위→1위, README #33)"""
    out = law_rag_tool.expand_legal_terms("폭발 위험 분위기에서의 작업 기준은?")
    assert "폭발위험장소" in out
    assert out.startswith("폭발 위험 분위기")


def test_expand_legal_terms_noop_without_trigger():
    q = "안전관리자 선임 기준은?"
    assert law_rag_tool.expand_legal_terms(q) == q
