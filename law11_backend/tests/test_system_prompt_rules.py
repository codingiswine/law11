"""SYSTEM_PROMPT의 필수 규칙 회귀 테스트 (#72).

프롬프트는 코드처럼 리뷰되지 않아 한 줄이 조용히 빠져도 아무도 모른다.
빠진 결과는 테스트가 아니라 eval에서 수치로만 드러나고(그마저 노이즈에
묻힌다), 운영에서는 틀린 법적 안내로 나간다. 그래서 "있어야 하는 규칙"을
문자열로 고정한다.

여기 있는 규칙은 전부 실측으로 필요성이 확인된 것만 넣는다.
"""
from app.tools.law_rag_tool import SYSTEM_PROMPT, WEB_SYSTEM_PROMPT
from app.tools._web_utils import UNTRUSTED_RULE


def test_조건부_분기_보존_규칙이_있다():
    """#71에서 발견한 GS-024 회귀를 막는 규칙 (#72).

    중대재해처벌법 제10조는 가목(1년 이상·10억원)과 나목·다목(7년 이하·1억원)으로
    처벌이 갈리는데, "결론은 한두 문장" 규칙에 눌려 조건이 떨어져 나갔다.
    같은 상황에 두 처벌이 적용되는 것처럼 읽혀 가장 무거운 쪽이 가벼워 보였다.
    실측: 규칙 추가 전 3/3 실패 → 추가 후 3/3 성공.
    """
    assert "조건에 따라 결과를 나누는 경우" in SYSTEM_PROMPT
    # "조건"이 아니라 "가르는 조건"이어야 한다. 1차 수정 때 그냥 "적용 조건"이라
    # 썼더니 모델이 분기들이 공유하는 전제("제4조 또는 제5조를 위반하여")로 해석해
    # GS-023에서 두 항목의 조건 문구가 똑같아졌다 — 항목만 나뉘고 내용은 그대로였다.
    assert "그 결과를 가르는 조건" in SYSTEM_PROMPT
    assert "분기들이 공유하는" in SYSTEM_PROMPT
    # 모델이 스스로 확인할 수 있는 점검 문장
    assert "조건 문구가 서로 같다면" in SYSTEM_PROMPT
    # 간결성이 정확성을 이기지 않는다는 우선순위
    assert "조건 보존을 우선" in SYSTEM_PROMPT


def test_할루시네이션_방지_원칙이_최우선으로_남아있다():
    """이 프롬프트의 존재 이유 — 지워지면 안 된다."""
    assert "[할루시네이션 방지 — 최우선 원칙]" in SYSTEM_PROMPT
    assert "제공된 조문에서 확인되지 않습니다" in SYSTEM_PROMPT


def test_웹_경로에_신뢰경계_규칙이_있다():
    """#64 — 웹 검색 결과가 지시로 읽히지 않게 하는 규칙."""
    assert UNTRUSTED_RULE in WEB_SYSTEM_PROMPT
