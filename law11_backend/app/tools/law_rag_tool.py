#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
law_rag_tool_async_v6.11_direct_article_linked.py
────────────────────────────────────────────
✅ 주요 개선
1️⃣ "법령명 + 조문번호" 질의 시 단순 포맷 출력
   → 법 설명 / 조문 전문 / 법령 정보(하이퍼링크 포함)
2️⃣ 시행일자는 DB 값만 표시 (GPT 생성 금지)
3️⃣ 출처는 [법령명 제n조](링크) 하이퍼링크로 표시
────────────────────────────────────────────
"""

import re, urllib.parse, aiohttp


def _extract_web_citations(answer: str) -> list:
    """웹 fallback 답변 텍스트에서 법령명+제N조 패턴 추출.

    ⚠️ 프롬프트는 "[법령명] 제X조" 대괄호 형식을 요청하지만, GPT가 온도>0
    영향으로 "**법령명** 제X조"처럼 볼드 마크다운으로 답할 때가 있다 (실측:
    "산업안전보건법이랑 중대재해처벌법 처벌 수위 차이" 질문에서 답변 본문은
    구체적 조문을 인용했는데 대괄호 정규식이 매치 안 돼 출처 배지가 하나도
    안 뜸 — 사용자가 답변 내용을 검증할 방법이 없었음). 대괄호/볼드 둘 다
    매치하도록 확장.
    """
    # GPT가 쓰는 인용 표기 변형들 (전부 실측으로 발견된 형태만):
    #   ① "[법령명] 제X조" — 프롬프트가 요청한 기본 형태
    #   ② "**법령명** 제X조" — 볼드 변형 (#12)
    #   ③ "[법령명 제X조]" — 조문 번호까지 대괄호 안에 넣는 변형 (#34, 실측:
    #      "[소방시설 설치 및 관리에 관한 법률 제8조]"가 매치 안 돼 배지 미표시)
    patterns = [
        r'(?:\[([^\]]{2,30}?)\]|\*\*([^\*\n]{2,30}?)\*\*)\s*제(\d+(?:의\d+)?)조',
        r'\[([^\]]{2,30}?)\s*제(\d+(?:의\d+)?)조[^\]]{0,12}\]',
    ]
    matches = []
    for pi, pattern in enumerate(patterns):
        for m in re.finditer(pattern, answer):
            if pi == 0:
                law_name, article = (m.group(1) or m.group(2)).strip(), m.group(3)
            else:
                law_name, article = m.group(1).strip(), m.group(2)
            matches.append((m.start(), law_name, article))

    citations = []
    seen = set()
    for _, law_name, article in sorted(matches):
        key = f"{law_name}:{article}"
        if key not in seen:
            seen.add(key)
            citations.append({
                "law_name": law_name, "article_number": article,
                "score": None, "rank": len(citations) + 1,
            })
        if len(citations) >= 5:
            break
    return citations
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from sqlalchemy import text
from qdrant_client.http.models import FieldCondition, MatchAny, MatchValue, Filter
from core.stream import ToolChunk
from app.tools.websearch_tool import summarize_web
from app.tools._web_utils import UNTRUSTED_RULE, fence_untrusted
from app.services.embedding_cache import get_embedding_async
try:
    from app.config import settings   # ✅ Docker 실행 시
except ModuleNotFoundError:
    from app.config import settings  # ✅ 로컬 실행 시



# ─────────────────────────────
# 환경 설정
# ─────────────────────────────
qdrant = settings.qdrant_client
async_engine = settings.async_engine
COLLECTION = settings.QDRANT_COLLECTION_NAME


# ─────────────────────────────
# 공통 시스템 프롬프트
# ─────────────────────────────
SYSTEM_PROMPT = """
너는 대한민국 산업안전보건 법령 전문가 AI 어시스턴트다.
다음 규칙을 반드시 준수하여 법령 기반 답변을 생성한다.

[할루시네이션 방지 — 최우선 원칙]
- DB/Qdrant에서 조문이 제공된 경우: 반드시 해당 조문 텍스트에 명시된 내용만 인용한다.
  조문에 없는 수치(기간, 인원, 금액, 면적 등), 조건, 처벌 내용을 추론하거나 생성하지 않는다.
  확인할 수 없는 내용이 필요할 경우 "해당 내용은 제공된 조문에서 확인되지 않습니다"라고 명시한다.
- Web fallback으로 조문이 제공된 경우: 웹에서 검색된 법조문 내용을 출처와 함께 제공한다.
  이 경우에도 검색 결과에 없는 내용을 임의로 추가하지 않는다.
- 어떤 경우에도 조문 번호(제X조, 제X항)를 임의로 만들거나 다른 조문 내용과 혼용하지 않는다.

[인용 방식 — 원문을 지킨다]
- 조문을 인용할 때는 제공된 조문 텍스트의 표현을 그대로 옮긴다. 쉬운 말로 바꾸거나 요약하지 않는다.
- 질문과 관련 없는 항·호는 통째로 생략한다. 생략은 하되, 남긴 부분은 원문 그대로 둔다.
- 조문 번호와 항 번호를 함께 표기한다. (예: 산업안전보건법 제17조제1항)

[법 적용 판단 우선 원칙]
모든 법령 인용은 다음 3단계 순서를 따른다.
1단계(사실 판단): 사용자 질문에서 위험 징후 또는 상황 조건을 먼저 파악한다.
2단계(적용 요건 판단): 해당 법 조문의 적용 요건이 충족되는지 판단한다.
3단계(법령 인용): 적용 요건이 충족되는 경우에만 해당 법 조문을 인용한다.
※ 단순히 '오래됨', '일반적 상황', '추상적 위험'만으로는 법을 적용하지 않는다.
※ 이 3단계는 사고 순서이지 출력 형식이 아니다. 판단 과정을 단계별로 나열하지 않는다.

[법 조문 역할 구분]
- 적용 요건: 법이 적용되는 조건
- 행위 의무: 해야 하는 행동
- 기술 기준: 구조, 수치, 설계 기준
※ 설치 기준(기술 기준)을 안전성 평가 기준으로 혼용하지 않는다.

[질문 의도 분석]
- "어떻게" → 절차/방법 중심으로 답변
- "법적 근거" → 조문 중심으로 답변
- "가능한가" → 판단 및 결론 중심으로 답변
※ 질문 의도와 맞지 않는 방식으로 답변하지 않는다.

[답변 구성 원칙]
1. 결론 — 질문에 대한 답을 한두 문장으로 먼저 말한다.
※ 다만 조문이 조건에 따라 결과를 나누는 경우(예: 가목은 A, 나목·다목은 B),
   각 결과에 **그 결과를 가르는 조건**을 반드시 붙여 말한다. 분기들이 공유하는
   전제(예: "제4조 또는 제5조를 위반하여")만 적고 갈라놓는 조건(가목 / 나목·다목 등)을
   빠뜨리면, 같은 상황에 서로 다른 결과가 적용되는 것처럼 읽혀 사실과 달라진다.
   → 자기 점검: 항목을 나눴는데 항목들의 조건 문구가 서로 같다면 가르는 조건을
     빠뜨린 것이다. 반드시 각 항목에 그 조건을 넣어 다시 쓴다.
   이때는 분기 수만큼 항목을 나눠 쓰고, "한두 문장" 제약보다 조건 보존을 우선한다.
2. 근거 조문 — 관련된 항·호의 원문을 그대로 인용한다.
※ 결론에서 한 말을 근거 조문 앞뒤로 다시 풀어쓰지 않는다. 같은 내용을 두 번 말하지 않는다.
※ 질문이 묻지 않은 적용 방법·절차·주의사항을 별도 항목으로 덧붙이지 않는다.
   다만 질문이 "어떻게"를 묻는 경우에는 절차가 곧 결론이므로 결론에 포함해 답한다.

[금지 사항]
- 조건 판단 없이 법령을 바로 인용하는 것 금지
- 조문에 없는 내용을 "일반적으로", "보통은" 등으로 포장해 추가하는 것 금지
- 설치 기준을 평가 기준처럼 사용하는 것 금지
- 질문 의도와 다른 방향으로 설명하는 것 금지
- 조문 원문을 쉬운 말로 바꿔 쓰는 것 금지 (원문 인용과 설명을 섞지 않는다)

[언어 규칙]
법적 근거(조문 원문 인용) 외의 모든 설명은 반드시 존댓말(합쇼체)로 작성한다.

[핵심 원칙]
법령은 '많이 아는 것'이 아니라 '정확한 상황에서 올바르게 적용하는 것'이 중요하다.
DB 조문이 있으면 해당 조문만을 근거로, 웹 fallback 시에는 웹에서 가져온 법조문을 출처와 함께 제공한다.
"""

WEB_SYSTEM_PROMPT = ("""너는 대한민국 법령 전문가 AI 어시스턴트다.
법령 데이터베이스에 해당 조문이 없어 웹 검색 결과를 바탕으로 답변한다.

[답변 원칙]
- 웹 검색 결과에서 확인된 법령명과 조문 번호를 명시해 법적 근거를 제시한다.
- 정확한 조문 번호를 확인할 수 없는 경우 "(참고 기준)"임을 표시한다.
- 면적, 개수, 거리 등 수치 기준은 출처와 함께 제시한다.
- 실무자가 바로 적용할 수 있도록 구체적으로 작성한다.
- 모든 설명은 존댓말(합쇼체)로 작성한다.

[금지 사항]
- 근거 없이 수치나 조건을 임의로 생성하는 것 금지
- "일반적으로", "보통은" 등으로 포장해 확인되지 않은 내용을 추가하는 것 금지
- 조문 원문을 따옴표로 직접 인용하는 것 금지 — 웹 검색 결과는 요약·기사이지 조문 원문이
  아니다. 따옴표 안에 넣으면 요약문이 원문으로 둔갑한다 (#94)
"""
    + UNTRUSTED_RULE
)


# ─────────────────────────────
# 유틸 함수
# ─────────────────────────────
def normalize_law_name(name: str) -> str:
    import unicodedata
    return re.sub(r"[\s·]", "", unicodedata.normalize("NFC", name.strip()))

def normalize_article(article: str) -> str:
    """조문번호 정규화 — 가지조문 보존: "제14조의2"/"14조의2"/"14의2" → "14의2", "제17조" → "17"

    ⚠️ 예전 구현(숫자만 추출)은 "제14조의2"를 "142"로 만들어 제142조와
    오매칭했다 (v1.6.0에서 수정). DB의 article_number_norm과 반드시 같은
    스킴("N" 또는 "N의M")을 유지해야 한다 — law_updater_async와 한 쌍.
    """
    s = article or ""
    m = re.search(r"(\d+)\s*(?:조)?\s*의\s*(\d+)", s)
    if m:
        return f"{m.group(1)}의{m.group(2)}"
    return re.sub(r"[^\d]", "", s)


def article_display(norm: str) -> str:
    """norm("14" | "14의2") → 표시형("제14조" | "제14조의2")"""
    n, _, b = (norm or "").partition("의")
    return f"제{n}조의{b}" if b else f"제{n}조"


# ── 법령 용어 매핑 (질의 확장) ─────────────────────────────────
# 사용자 표현 ↔ 법령 공식 용어가 어긋나면 임베딩 검색이 엉뚱한 조문을 상위로
# 올린다 (실측: "폭발 위험 분위기" 질의가 발파 조문을 검색 — 규칙의 공식 용어는
# "폭발위험장소"라서. 용어 부착 시 제230조가 4위→1위, README #33).
# ⚠️ 전역 어휘 부스트는 실험에서 기각됨(다른 케이스 최대 7건 회귀) — 여기에는
# 실측으로 검증된 매핑만 추가한다. 트리거는 공백 제거 정규형으로 비교.
_LEGAL_TERM_MAP = [
    ("폭발위험분위기", "폭발위험장소"),
    # "적정공기"의 수치 기준(산소 18~23.5% 등)은 제618조(정의)에만 있는데, 정의 조문은
    # 용어 5개를 한 덩어리로 담고 있어 수치를 묻는 질문과 멀다 — 실측 8위(0.51)로 top-5
    # 밖. 정의 조문임을 붙이면 1위(0.60). 안 붙이면 모델이 "법령에 명시된 바 없다"고
    # 단정했다 (#93).
    ("적정공기", "적정공기의 정의"),
]


def expand_legal_terms(query: str) -> str:
    """임베딩 검색용 질의 확장 — 매핑된 법령 공식 용어를 부착 (표시/저장에는 미사용)."""
    q_norm = re.sub(r"\s+", "", query)
    for trigger, term in _LEGAL_TERM_MAP:
        if trigger in q_norm and term not in q_norm:
            return f"{query} (관련 법령 용어: {term})"
    return query

def detect_law_name(query: str) -> Optional[str]:
    """질문 내에서 법령명 자동 감지"""
    LAWS = [
        "산업안전보건기준에관한규칙", "산업안전보건법시행규칙", "산업안전보건법시행령", "산업안전보건법",
        "재난및안전관리기본법시행규칙", "재난및안전관리기본법시행령", "재난및안전관리기본법",
        "중대재해처벌등에관한법률시행령", "중대재해처벌등에관한법률"
    ]
    q = re.sub(r"\s+", "", query)
    for law in LAWS:
        if law in q:
            return normalize_law_name(law)
    return None


# ⚠️ 할루시네이션 방지: "OOO법 N조"처럼 구체적 법명+조문을 물었는데 그 법이
# 우리 9개 법 목록(detect_law_name)에 없는 경우를 감지한다. 이 경우 전체
# 말뭉치 의미검색(Qdrant)은 다른 법의 유사 조문을 threshold 이상으로 찾아올 수
# 있고, GPT가 그 내용을 "사용자가 물은 법의 조문인 것처럼" 잘못 인용하는
# 위험이 있다 (실측: "소방기본법 2조"가 재난및안전관리기본법 조문을 근거로
# "[소방기본법] 제2조"라고 사칭해 답변 — 배지는 실제 검색된 법을 정직하게
# 보여줬지만 본문과 안 맞았음). "관련법 뭐있어?"처럼 조문 번호 없는 일반
# 질문은 이 패턴에 안 걸리므로 기존 넓은 의미검색 경로를 그대로 탄다.
_UNKNOWN_LAW_HINT = re.compile(r"[가-힣]{2,15}(?:법률|법|규칙|시행령)\s*(?:제)?\s*\d+\s*조")


def mentions_unknown_law(query: str, known_law_name: Optional[str], article_number: str) -> bool:
    if known_law_name or not article_number:
        return False
    return bool(_UNKNOWN_LAW_HINT.search(query))


# ─────────────────────────────
# 🚧 스코프 경계 게이트 (로드맵 P3)
#
# 조문 검색이 모두 빗나간 질문은 유료 웹 경로(Tavily·Naver + 긴 웹 컨텍스트 GPT
# 호출)로 떨어진다. 2026-10-21 적대적 트래픽 실측: 306건 중 **302건(98.7%)**이
# 웹으로 갔고, 그 질문들은 "deploy 권한이 있나", "As visitor, I need authorization
# to use Blog Search" 같은 **법령 질문이 아예 아닌 것들**이었다. 무인증 엔드포인트에
# 관계없는 질문을 반복해 던지는 것만으로 비용이 선형 증가한다.
#
# "범위 밖"을 일반적으로 판정하는 것은 여전히 어렵다(개념형 법령 질문). 그래서
# **도메인 자체가 빗나간 하위 집합만** 거른다 — 한국어 비율이 낮고 법령 용어가
# 하나도 없는 질문. 두 조건을 **모두** 요구하는 이유는 한글 비율만 보면
# "OSHA 제17조?"처럼 짧은 혼용 질문이 걸리고, 용어만 보면 "위험성평가란
# 무엇인가요?"처럼 용어 목록에 없는 정상 질문이 걸리기 때문이다.
#
# 실측(운영 로그 678행, 2026-11-10 재생 — LLM 호출 0회):
#   · 웹 폴백 460건 중 177건 차단 (38%)
#   · **오탐 0건** — DB가 실제로 답한 218건(pg 69 · qdrant 149) 중 걸리는 것이 없다
#   · 차단 177건은 **전부 2026-10-21 적대적 트래픽**이고, 정상 11일의 웹 폴백
#     158건은 하나도 건드리지 않는다 (소화기·수영장·근로기준법 같은 DB 범위 밖
#     한국어 법령 질문은 그대로 웹 답변을 받는다)
#
# ⚠️ 오탐 0건의 표본은 자체 테스트 트래픽이다. 영어로 묻는 정상 사용자는 막힌다 —
#    한국어 법령 서비스라는 전제를 받아들인 결과이고, 안내 문구로 그 전제를 밝힌다.
#    게이트는 **웹 폴백 직전에만** 둔다. PG·Qdrant 경로 앞에 두면 DB가 답할 수 있는
#    질문을 막을 수 있는데, 지금 위치에서는 구조적으로 불가능하다.
# ─────────────────────────────
_HANGUL = re.compile(r"[가-힣]")
_LAW_TERM = re.compile(
    r"법|조|항|호|규칙|시행령|시행규칙|판례|처벌|의무|기준|안전|보건|재해|사고|근로|사업주|노동"
)
OUT_OF_DOMAIN_HANGUL_RATIO = 0.3

OUT_OF_SCOPE_MESSAGE = (
    "이 질문은 제가 다루는 범위를 벗어난 것으로 보입니다.\n\n"
    "저는 산업안전보건 분야 9개 법령(산업안전보건법·중대재해처벌등에관한법률·"
    "산업안전보건기준에 관한 규칙 등)의 조문을 근거로 답변합니다. "
    "법령·조문·안전보건 기준에 관해 **한국어로** 질문해 주시면 해당 조문을 찾아 "
    "답변해 드리겠습니다."
)


def is_out_of_domain(query: str) -> bool:
    """법령 질문의 형태를 아예 갖추지 않은 질문인가. **웹 폴백 직전에만** 쓴다."""
    compact = query.replace(" ", "")
    if not compact:
        return True
    hangul_ratio = len(_HANGUL.findall(compact)) / len(compact)
    return hangul_ratio < OUT_OF_DOMAIN_HANGUL_RATIO and not _LAW_TERM.search(query)


# ─────────────────────────────
# 조건 기반 법령 우선순위 매핑
# 단순 유사도 검색이 아닌, 질문의 위험 유형으로 법령 범위를 좁힌다.
# ─────────────────────────────
_CONDITION_LAW_MAP = [
    # (트리거 키워드 집합, 우선 검색할 법령_norm)
    ({"균열", "침하", "붕괴", "변형", "결함", "파손", "노후"},      "산업안전보건기준에관한규칙"),
    ({"계단", "난간", "추락", "미끄럼", "발판"},                    "산업안전보건기준에관한규칙"),
    ({"비계", "거푸집", "동바리", "족장", "가시설"},               "산업안전보건기준에관한규칙"),
    ({"굴착", "발파", "터널", "흙막이", "사면"},                   "산업안전보건기준에관한규칙"),
    ({"크레인", "리프트", "달비계", "곤돌라", "양중"},             "산업안전보건기준에관한규칙"),
    ({"밀폐공간", "산소결핍", "유해가스", "환기"},                  "산업안전보건기준에관한규칙"),
    ({"화재", "소화", "피난", "방화", "폭발", "인화"},              "산업안전보건기준에관한규칙"),
    # 선임 인원·자격은 법이 시행령(제16조 → 별표 3 등)에 맡긴다. 법만 좁히면 시행령 조문이
    # 2위인데도 빠져, 모델이 숫자를 지식으로 채웠다 (#95). 우선 법령은 여러 개일 수 있다.
    ({"안전관리자", "보건관리자", "선임", "위탁", "관리감독자"},     ("산업안전보건법", "산업안전보건법시행령")),
    ({"중대재해", "경영책임자", "처벌", "징역"},                     "중대재해처벌등에관한법률"),
    ({"재난", "대응", "복구", "위기관리"},                           "재난및안전관리기본법"),
]

def get_priority_law(query: str) -> Optional[list]:
    """키워드 조건에 따라 우선 검색할 법령_norm 목록 반환. 없으면 None."""
    q = re.sub(r"\s+", "", query)
    for keywords, laws in _CONDITION_LAW_MAP:
        if any(k in q for k in keywords):
            laws = (laws,) if isinstance(laws, str) else laws
            return [normalize_law_name(l) for l in laws]
    return None


# ── 후속 질문 검색어 보강 (#96) ─────────────────────────────
# "그럼 그 측정은 누가 해야 해?"처럼 지시어로 앞 턴을 가리키는 짧은 질문은 그 문장만
# 임베딩하면 무관한 조문이 올라온다 (실측: 제619조의2 대신 53·184·125·284·189).
# 이전 대화는 생성 단계에만 들어가고 검색은 현재 문장만 보고 있었다. 직전 사용자
# 질문을 **임베딩 입력에만** 덧붙인다 — 법령명·조문번호 파싱과 우선 법령은 현재
# 질문만 본다(앞 턴의 "제38조"가 PG 정확매칭을 가로채면 안 되므로).
# ponytail: 지시어 목록 + 길이 휴리스틱. 틀리는 사례가 쌓이면 LLM 재작성으로 올린다.
_FOLLOW_UP_HINT = re.compile(r"(^|\s)(그럼|그러면|그렇다면|그거|그건|그게|그것|그런|이거|이건|저거|거기|그때|그)\s")


def prior_user_question(query: str, context: str) -> str:
    """지시어가 든 짧은 후속 질문이면 직전 사용자 질문을, 아니면 빈 문자열."""
    if not context or len(query) > 40 or not _FOLLOW_UP_HINT.search(query + " "):
        return ""
    prev = [ln[len("사용자: "):].strip() for ln in context.splitlines() if ln.startswith("사용자: ")]
    return prev[-1] if prev else ""


# ── 시행 예정 표시 (#97) ─────────────────────────────────────
# 법제처 DRF를 법령 ID로 호출하면 **최신 공포본**이 온다 — 아직 시행 전인 개정판이다.
# 산업안전보건법은 2026-10-27 공포(22122)·2027-04-28 시행판이 통째로 저장돼 188개 조문
# 전부 시행일자 2027-04-28이고, 그중 18개는 본문도 아직 시행되지 않은 개정 후 내용이다.
# 오늘 시행 중인 판은 이 키로는 받을 수 없어(연혁 API 미제공, efYd 무시) 본문은 그대로
# 두고, 날짜가 미래면 사용자에게 그 사실을 알린다.
# ponytail: 바뀌지 않은 170개 조문까지 같이 경고한다(과잉 경고 쪽이 안전). 연혁 API가
# 열리면 시행예정판들의 조문변경여부 합집합으로 바뀐 조문만 표시하도록 좁힌다.
def enforcement_notice(enforcement_date, today=None) -> str:
    """시행일자가 오늘보다 뒤면 경고 문구, 아니면 빈 문자열."""
    if not enforcement_date:
        return ""
    today = today or datetime.now().date()
    d = enforcement_date if hasattr(enforcement_date, "year") else None
    if d is None:
        try:
            d = datetime.strptime(str(enforcement_date)[:10], "%Y-%m-%d").date()
        except ValueError:
            return ""
    if d <= today:
        return ""
    return (f" ⚠️ **시행 예정** — 이 날짜에 시행되는 개정판 기준이며, "
            f"현재 시행 중인 조문과 본문이 다를 수 있습니다")


def _prepend_context(context: str, content: str) -> str:
    if not context:
        return content
    return f"[이전 대화]\n{context}\n\n{content}"


# ─────────────────────────────
# 계층형 검색 (운영 run() ↔ eval/retriever.py 단일 소스)
# ─────────────────────────────
_ARTICLE_RE = re.compile(r"(?:제)?\s*(\d+)\s*조(?:\s*의\s*(\d+))?")


def parse_article_number(query: str) -> str:
    """질문에서 조문 번호를 'N' / 'N의M' 스킴으로 추출. 없으면 빈 문자열."""
    m = _ARTICLE_RE.search(query)
    if not m:
        return ""
    return m.group(1) + (f"의{m.group(2)}" if m.group(2) else "")


@dataclass
class LawSearch:
    """계층형 검색 결과 (PG → Qdrant → Web).

    source: "pg" | "qdrant" | "web" | "missing" | "db_error"
      · missing  — 법령명+조문번호를 물었는데 그 조문이 DB에 없음 (대체 검색 금지)
      · db_error — PG 장애 + Qdrant 대체 조회까지 실패
    articles: [{"law_name", "article_number", "text", "score"}]
    steps:    SSE로 흘려보낼 상태 메시지 (호출부가 yield)
    """
    source: str
    law_name: Optional[str]
    article_number: str
    is_direct_article: bool
    articles: List[Dict]
    enforcement_date: Optional[str] = None
    steps: List[str] = field(default_factory=list)


async def search_law_articles(query: str, prior_question: str = "") -> LawSearch:
    """법령 조문 계층형 검색 — 운영과 평가가 반드시 이 함수 하나만 쓴다.

    ⚠️ 예전에는 run()과 eval/retriever.py가 검색 우선순위를 각자 구현했고,
    30개 골든셋 중 3건에서 서로 다른 조문으로 돌고 있었다 (실측 2026-10-27):
      · GS-013·GS-027 — 평가 쪽에 threshold 게이트가 없어서, 운영이 웹 폴백으로
        넘기는 저유사도 결과(0.3548 / 0.4106)를 RAGAS 채점 근거로 쓰고 있었다.
      · GS-026 — 평가 쪽에 '법령명 인식' 경로가 없어서, 운영이 1건(법령 필터
        + threshold 0.5)만 쓰는 질문에 5건(priority 필터 + 0.45)을 넘기고 있었다.
    즉 RAGAS 수치가 사용자가 실제로 타는 경로를 측정하지 않고 있었다. 검색
    경로를 새로 붙일 때(MCP 등) 이 함수를 호출할 것 — 네 번째 사본을 만들지 않는다.
    """
    law_name = detect_law_name(query)
    article_number = parse_article_number(query)
    embed_text = f"{prior_question} {query}".strip() if prior_question else query   # #96
    found = LawSearch(
        source="web",
        law_name=law_name,
        article_number=article_number,
        is_direct_article=bool(law_name and article_number),
        articles=[],
    )

    # ① 법령명 미인식 → 조건 기반 우선 법령으로 좁힌 뒤 의미 검색
    if not law_name:
        found.steps.append("🧠 [Qdrant] 전체 법령 의미 검색 중...")
        try:
            embedding = await get_embedding_async(expand_legal_terms(embed_text))
            priority_law = get_priority_law(query)
            q_filter = (
                Filter(must=[FieldCondition(key="law_name_norm", match=MatchAny(any=priority_law))])
                if priority_law else None
            )
            results = await qdrant.search(COLLECTION, embedding, query_filter=q_filter, limit=10, with_payload=True)
            # 우선 법령 검색에서 결과가 부족하면 전체 재검색
            if (not results or results[0].score < 0.45) and priority_law:
                results = await qdrant.search(COLLECTION, embedding, limit=10, with_payload=True)
            # ⚠️ Cross-Encoder 리랭킹 제거 (v1.5.0): ms-marco-MiniLM은 영어 전용이라
            # 한국어 조문을 사실상 무작위 재배열했음 — 교정된 골든셋 30케이스 실측에서
            # Top-1 66.7%(벡터 순서) → 13.3%(EN CE), 다국어 CE도 벡터를 못 이김
            # (eval/_rerank_experiment.py). 벡터 코사인 순서 상위 5개를 그대로 쓴다.
            results = results[:5]
            # 0.45: 법령명 미인식 상태의 전체 검색이므로 넓게 허용.
            # 사용자가 법령 용어를 쓰지 않아도 관련 조문을 건질 수 있어야 한다.
            # 단, unknown_law_hint(구체적 법명+조문을 물었는데 그 법이 DB에
            # 없는 경우)면 threshold를 넘겨도 신뢰하지 않고 웹 폴백으로 보낸다.
            if results and results[0].score >= 0.45 and not mentions_unknown_law(query, law_name, article_number):
                seen = set()
                for hit in results:
                    text_val = hit.payload.get("text", "")
                    key = (hit.payload.get("law_name", ""), hit.payload.get("article_number_norm", ""))
                    if text_val and key not in seen:   # 중복 조문 제거
                        seen.add(key)
                        found.articles.append({
                            "law_name": key[0], "article_number": key[1],
                            "text": text_val, "score": hit.score,
                        })
                # ✅ 화면에 표시되는 %(Qdrant 코사인 유사도)와 배지 순서가 일치하도록
                # 코사인 점수 내림차순 정렬 유지
                found.articles.sort(key=lambda a: a["score"], reverse=True)
                found.source = "qdrant"
                found.steps.append(f"✅ [Qdrant] 관련 조문 {len(found.articles)}개 발견")
                return found
        except Exception as e:
            print(f"⚠️ Qdrant 검색 실패: {e}")
            found.steps.append("⚠️ Qdrant 검색 실패 → 대체 경로 진행")
        found.steps.append("⚠️ 관련 법령 없음 → Web 검색으로 보완")
        return found

    law_norm = normalize_law_name(law_name)

    # ② 법령명 + 조문번호 → PostgreSQL 정확 매칭
    # (조문번호가 없으면 article_number_norm='' 로 조회하는 셈이라 어차피 0건 — 건너뛴다)
    if article_number:
        pg_error = False
        try:
            async with async_engine.connect() as conn:
                row = (await conn.execute(
                    text("""
                        SELECT text, enforcement_date
                        FROM law_chunks
                        WHERE law_name_norm = :law AND article_number_norm = :num
                        LIMIT 1;
                    """),
                    {"law": law_norm, "num": normalize_article(article_number)},
                )).fetchone()
            if row:
                found.source = "pg"
                found.enforcement_date = row[1]
                found.articles = [{
                    "law_name": law_name, "article_number": article_number,
                    "text": row[0], "score": 1.0,
                }]
                found.steps.append("✅ [PostgreSQL] 조문 발견")
                return found
        except Exception as e:
            pg_error = True
            print(f"⚠️ [PostgreSQL] 조회 실패: {e}")
            found.steps.append("⚠️ [PostgreSQL] 오류 → 대체 경로 진행")

        # 조문 번호가 명시된 직접 조회에서 PG miss는 "해당 조문 없음"을 의미 —
        # Qdrant로 다른 조문을 대신 꺼내지 않는다.
        if not pg_error:
            found.source = "missing"
            return found

        # ⚠️ PG "오류"와 "row 없음"을 반드시 구분한다. 장애 주입 실측: PG가 죽었을 때
        # 이 분기가 "제17조는 데이터베이스에 존재하지 않습니다"라고 답했다 — 인프라
        # 장애를 조문 부재로 오보하는 허위 응답 (README #31). 오류 시에는 Qdrant에
        # 같은 조문이 norm 필터로 존재하므로 scroll 정확 조회로 대체하고, 그마저
        # 실패하면 정직하게 일시 오류를 안내한다.
        try:
            points, _ = await qdrant.scroll(
                COLLECTION,
                scroll_filter=Filter(must=[
                    FieldCondition(key="law_name_norm", match=MatchValue(value=law_norm)),
                    FieldCondition(key="article_number_norm", match=MatchValue(value=normalize_article(article_number))),
                ]),
                limit=1,
                with_payload=True,
            )
            if points:
                p = points[0].payload
                found.source = "qdrant"
                found.enforcement_date = p.get("enforcement_date", "")
                found.articles = [{
                    "law_name": law_name, "article_number": article_number,
                    "text": p.get("text", ""), "score": 1.0,
                }]
                found.steps.append("✅ [Qdrant] 대체 정확 조회 성공 (PG 장애)")
                return found
        except Exception as e2:
            print(f"⚠️ [Qdrant] 대체 조회도 실패: {e2}")
        found.source = "db_error"
        return found

    # ③ 법령명만 인식 → 해당 법령 안에서만 의미 검색
    found.steps.append("🧠 [Qdrant] 벡터 검색 중...")
    try:
        embedding = await get_embedding_async(expand_legal_terms(embed_text))
        q_filter = Filter(must=[FieldCondition(key="law_name_norm", match=MatchValue(value=law_norm))])
        results = (await qdrant.search(COLLECTION, embedding, query_filter=q_filter, limit=10, with_payload=True))[:5]
        # 0.50: 이미 법령명으로 범위를 좁혔는데 여기서도 미달이면
        # 해당 법령 DB에 답이 없다는 신호 → web fallback이 더 정확.
        # ①(0.45)보다 엄격한 이유: 검색 범위가 좁을수록 낮은 score = 진짜 없음.
        if results and results[0].score >= 0.5:
            best = results[0]
            found.source = "qdrant"
            found.enforcement_date = best.payload.get("enforcement_date", "")
            found.articles = [{
                "law_name": best.payload.get("law_name", law_name),
                "article_number": best.payload.get("article_number_norm", ""),
                "text": best.payload.get("text", ""),
                "score": best.score,
            }]
            found.steps.append(f"✅ [Qdrant] 유사도 {best.score:.2f} 조문 발견")
            return found
    except Exception as e:
        print(f"⚠️ Qdrant 검색 실패: {e}")
        found.steps.append("⚠️ Qdrant 검색 실패 → 대체 경로 진행")
    found.steps.append("⚠️ 조문 없음 → Web fallback 실행")
    return found


# 웹 경로 답변 머리에 코드가 직접 붙이는 안내 — 모델에게 맡기면 빠뜨리고, 프론트에
# 배지를 달면 meta 청크를 SSE로 흘려야 한다(금지, CLAUDE.md). 본문 텍스트가 가장 싸고 확실하다 (#94).
WEB_SCOPE_NOTICE = (
    "> ⚠️ **수록 법령 범위 밖** — 이 답변은 웹 검색 결과를 바탕으로 작성됐습니다. "
    "조문 원문은 법제처(law.go.kr)에서 확인하십시오.\n\n"
)
# 검색은 됐지만 그 조문들에 답이 없어 웹으로 넘어간 경우 — 범위 밖이 아니라 검색 누락이다 (#98)
WEB_MISS_NOTICE = (
    "> ⚠️ **검색된 조문에 답이 없음** — 웹 검색 결과로 보완한 답변입니다. "
    "조문 원문은 법제처(law.go.kr)에서 확인하십시오.\n\n"
)

# ── 미확인 인정 → 웹 폴백 (#98) ─────────────────────────────
# 검색이 빈손이면 웹으로 가면서, 조문 5개가 왔는데 답이 없을 때는 "확인되지 않습니다"에서
# 멈추고 있었다. 모델이 미확인을 인정한 경우에만 웹으로 보낸다 — 빈손 검색과 같은 원칙.
# 결론은 보낸 뒤 되돌릴 수 없으므로 "판단 근거" 표시가 나올 때까지만 버퍼해 판정한다.
_CONCLUSION_MISS = re.compile(r"확인되지 않|확인할 수 없|확인되지 아니")
_HEAD_MARK = "판단 근거"


def conclusion_admits_miss(head: str) -> bool:
    """결론 구간(판단 근거 앞)이 '제공된 조문에서 확인되지 않음'인가."""
    return bool(_CONCLUSION_MISS.search(head.split(_HEAD_MARK)[0]))


async def _answer_from_web(query: str, context: str, is_direct_article_query: bool,
                           notice: str = WEB_SCOPE_NOTICE):
    """조문 검색 실패 시 웹 검색으로 보완. 운영 두 경로가 쓰던 동일 블록을 합친 것."""
    web_result = await summarize_web(query, context=context)
    # ⚠️ 검색 결과가 하나도 없으면 GPT 생성 자체를 중단한다. 장애 주입 실측:
    # 웹 소스(Tavily+Naver) 전멸 상태에서 "검색 결과 없음" 문구를 GPT에 넘기면
    # "소화기는 100㎡당 1개" 같은 수치 기준을 근거 0에서 지어내 법적 근거
    # 포맷으로 출력했다 (README #31). 법률 챗봇에서 근거 없는 확답은 오답보다 나쁘다.
    if not web_result.get("raw_results"):
        yield ToolChunk(type="text", payload="현재 웹 검색이 일시적으로 불가하여 관련 법령 정보를 확인할 수 없습니다. 잠시 후 다시 시도해 주시기 바랍니다.")
        yield ToolChunk(type="status", payload="⚠️ 웹 검색 결과 없음 — 근거 없는 답변 생성 중단")
        return

    resp = await settings.openai_client.chat.completions.create(
        model=settings.LLM_MODEL,
        timeout=settings.GPT_TIMEOUT_SECONDS,
        messages=[
            {"role": "system", "content": WEB_SYSTEM_PROMPT},
            {"role": "user", "content": _prepend_context(context, f"""질문: {query}

아래 검색 결과를 참고해 구체적인 조문 번호(제X조 제X항)를 명시하여 답변해.
법령명만 나열하지 말고, 해당 조문이 무엇을 규정하는지 내용과 함께 명시해.
⚠️ 조문 원문을 따옴표로 인용하지 마 — 검색 결과는 요약이지 원문이 아니다. 규정 내용은
   설명문으로 쓰고, 각 법적 근거 끝에 "(웹 검색 기준, 원문 확인 필요)"를 붙여.

[검색 결과]
{fence_untrusted(web_result.get("summaries", ""), "웹 검색 요약")}

출력 형식:
🔹 **결론** (한 문장 요약)
🔹 **판단 근거** (상황 조건 및 적용 요건)
🔹 **법적 근거**
  - [법령명] 제X조 제X항: (규정 내용을 설명문으로, 따옴표 없이) (웹 검색 기준, 원문 확인 필요)
🔹 **적용 방법** (제공된 조문에 명시된 사항만 정리 — 조문에 없는 일반적 안전관리 조언은 쓰지 마)
🔹 **출처** (법령명 + 조문번호)""")},
        ],
        temperature=0.2,
    )
    answer = resp.choices[0].message.content.strip()
    yield ToolChunk(type="text", payload=notice)
    yield ToolChunk(type="meta", payload={
        "query_type": "direct_article" if is_direct_article_query else "semantic",
        "selected_source": "web",
        "selected_articles": [],
        "fallback_used": True,
        "confidence_score": None,
        "tool": "law_rag_tool",
    })
    yield ToolChunk(type="text", payload=answer)
    web_cites = _extract_web_citations(answer)
    if web_cites:
        yield ToolChunk(type="source", payload={"retrieved_laws": web_cites})
    yield ToolChunk(type="status", payload="✅ Web 보완 검색 완료")


# ─────────────────────────────
# 핵심 실행 (Async)
# ─────────────────────────────
async def run(plan):
    query = plan.args.get("query", "")
    context = plan.args.get("context", "")
    yield ToolChunk(type="status", payload="⚖️ 법령 검색 시작...")

    found = await search_law_articles(query, prior_user_question(query, context))
    for step in found.steps:
        yield ToolChunk(type="status", payload=step)

    law_name = found.law_name
    article_number = found.article_number
    is_direct_article_query = found.is_direct_article

    if found.source == "missing":
        yield ToolChunk(type="text", payload=(
            f"**{law_name} {article_display(article_number)}**는 데이터베이스에 존재하지 않습니다.\n\n"
            f"조문 번호를 확인하시거나 법령명이 정확한지 검토해 주십시오."
        ))
        yield ToolChunk(type="status", payload="✅ 조회 완료 (조문 없음)")
        return

    if found.source == "db_error":
        yield ToolChunk(type="text", payload="일시적인 데이터베이스 오류로 조문을 조회하지 못했습니다. 잠시 후 다시 시도해 주시기 바랍니다.")
        yield ToolChunk(type="status", payload="⚠️ 조회 실패 (일시적 DB 오류)")
        return

    if found.source == "web":
        # 유료 경로 직전 스코프 경계 게이트 (P3). 여기서만 막으므로 DB가 답한
        # 질문은 구조적으로 영향을 받지 않는다.
        if is_out_of_domain(query):
            yield ToolChunk(type="meta", payload={
                "query_type": "direct_article" if is_direct_article_query else "semantic",
                "selected_source": "out_of_scope",
                "selected_articles": [],
                "fallback_used": False,
                "confidence_score": None,
                "tool": "law_rag_tool",
            })
            yield ToolChunk(type="text", payload=OUT_OF_SCOPE_MESSAGE)
            yield ToolChunk(type="status", payload="⛔ 범위 밖 질문 — 웹 검색 생략")
            return
        async for chunk in _answer_from_web(query, context, is_direct_article_query):
            yield chunk
        return

    # Ⓐ 법령명 미인식 + 의미 검색 성공 → 검색된 여러 조문을 한 번에 근거로 답변
    if not law_name:
        citations = [
            {"law_name": a["law_name"], "article_number": a["article_number"],
             "score": round(a["score"], 4), "rank": rank}
            for rank, a in enumerate(found.articles, start=1)
        ]
        combined = "\n\n".join(
            f"[{a['law_name']} {article_display(a['article_number'])}]\n{a['text']}" for a in found.articles
        )
        meta = ToolChunk(type="meta", payload={
            "query_type": "semantic",
            "selected_source": "qdrant",
            "selected_articles": [f"{a['law_name']} {article_display(a['article_number'])}" for a in found.articles],
            "citations": citations,
            "fallback_used": False,
            "confidence_score": found.articles[0]["score"] if found.articles else None,
            "tool": "law_rag_tool",
        })   # 결론 판정 뒤에 보낸다 — 웹으로 넘어가면 웹 경로의 meta만 남아야 한다 (#98)

        prompt = f"""너는 대한민국 산업안전보건 법령 전문가야.
사용자 질문: "{query}"
아래 법령 조문을 반드시 인용하여 실무 중심으로 답변해.
⚠️ 법적 근거(조문 원문 인용) 외의 모든 설명은 반드시 존댓말(합쇼체)로 작성해.
⚠️ [관련 법령 조문]에 제공된 조문은 전부 검토하고, 답변 내용에 실제로 사용한
   조문은 빠짐없이 [법적 근거]에 포함해 — 일부만 골라 인용하고 나머지 조문
   내용을 출처 없이 요약·적용 기준에 섞어 넣지 마.

출력 형식:
🔹 **결론** (한 문장 요약, 존댓말. 제공된 조문에 답이 없으면 "제공된 조문에서는 확인되지
  않습니다"라고 쓴다 — 제공된 조문은 검색 결과 일부라 "법령에 없다/명시된 바 없다"처럼
  법령 전체를 부정 단정하지 않는다. 조문이 "대통령령으로 정한다"·"별표 N과 같다"처럼 다른 규정에 맡기면 수치·인원은 그 규정(시행령·별표)에
  있다고 밝히고 제공된 조문만으로 숫자를 단정하지 않는다 — 별표는 이 DB에 없다.
  질문이 가리키는 법령·대상에 해당하는 조문이 없으면 다른 법령·다른 대상의 조문이나 수치로
  대신하지 않는다 — 예: 근로자 교육 시간을 경영책임자 교육 조문으로, 산업안전보건법 위반 처벌을
  재난법 벌칙으로 답하지 않는다. 처벌·결과가 항·목으로 갈리면 질문의 사실관계(사망·부상·질병 등)가
  해당하는 분기만 결론에 쓴다.)
🔹 **판단 근거** (이 조문이 적용되는 상황 조건·요건 — 조문에 "~하는 경우",
  "~한 때" 등 적용 조건이 명시돼 있으면 반드시 그 조건을 밝혀, 존댓말)
🔹 **법적 근거**
  - [법령명] 제X조 제X항: (조문 원문 또는 핵심 내용)
🔹 **적용 기준** (제공된 조문에 명시된 사항만 정리 — 조문에 없는 일반적 안전관리 조언은 쓰지 마, 존댓말)

[관련 법령 조문]
{combined}"""

        stream = await settings.openai_client.chat.completions.create(
            model=settings.LLM_MODEL,
            timeout=settings.GPT_TIMEOUT_SECONDS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _prepend_context(context, prompt)},
            ],
            temperature=0.2,
            stream=True,
        )
        # ponytail: 재검색 단계는 뺐다 — 미확인 사례의 정답(중대재해법 제3조)이 벡터 15위 밖이라
        # 같은 검색을 다시 해도 못 찾는다. 키워드 검색이 생기면 웹 앞에 끼운다.
        answer_parts, head, head_done, missed = [], [], False, False
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if not delta:
                continue
            if head_done:
                answer_parts.append(delta)
                yield ToolChunk(type="text", payload=delta)
                continue
            head.append(delta)
            joined = "".join(head)
            if _HEAD_MARK in joined or len(joined) > 300:
                head_done = True
                if conclusion_admits_miss(joined):
                    missed = True
                    break
                yield meta
                answer_parts.append(joined)
                yield ToolChunk(type="text", payload=joined)
        if not head_done:   # 판단 근거 표시 없이 끝난 짧은 답
            joined = "".join(head)
            if conclusion_admits_miss(joined):
                missed = True
            else:
                yield meta
                answer_parts.append(joined)
                yield ToolChunk(type="text", payload=joined)
        if missed:
            try:
                await stream.close()
            except Exception:
                pass
            yield ToolChunk(type="status", payload="🔁 검색된 조문에 답이 없음 → Web 검색으로 보완")
            async for c in _answer_from_web(query, context, is_direct_article_query, notice=WEB_MISS_NOTICE):
                yield c
            return

        # ⚠️ 프롬프트 지시("빠짐없이 인용")만으로는 GPT가 가끔 검색된 조문
        # 일부를 답변에서 빠뜨린다 (실측 확인, 2026-09-05 — 5개 중 2개
        # 누락되는 재현 사례 발견, temperature=0.2라 완전히 결정적이지
        # 않음). 코드 레벨에서 한 번 더 확인해 빠진 조문이 있으면 footer로
        # 명시한다 — 사용자가 검색은 됐지만 답변엔 없는 조문을 놓치지 않게.
        full_answer = "".join(answer_parts)
        missing = [c for c in citations if article_display(c["article_number"]) not in full_answer]
        if missing:
            missing_str = ", ".join(
                f"[{c['law_name']} {article_display(c['article_number'])}]" for c in missing
            )
            yield ToolChunk(type="text", payload=f"\n\n📎 **함께 검색된 조문** (위 답변에 직접 인용되지 않음, 참고): {missing_str}")

        yield ToolChunk(type="source", payload={"retrieved_laws": citations})
        yield ToolChunk(type="status", payload="✅ 법령 검색 완료")
        return

    # Ⓑ 단일 조문 확보 (PG 정확 매칭 또는 법령 필터 의미 검색)
    best = found.articles[0]
    text_val = best["text"]
    enforcement_date = found.enforcement_date
    selected_source = found.source
    selected_articles = [
        f"{best['law_name']} {article_display(best['article_number'])}" if best["article_number"] else best["law_name"]
    ]

    # ⑤ 조문 발견 시 GPT 요약
    # ⚠️ 인용은 질문에서 파싱한 law_name/article_number가 아니라 **검색이 실제로 찾은**
    # 조문(best)으로 만든다 (#82). ③ 경로(법령명만 인식 → 법령 필터 의미 검색)에서는
    # 질문에 조문번호가 없어 found.article_number == "" 이고, 그걸 쓰면 citations 테이블에
    # 빈 조문·URL에 "제조"가 들어갔다.
    cite_law, cite_art = best["law_name"], best["article_number"]
    pg_citations = [
        {
            "law_name": cite_law,
            "article_number": cite_art,
            "score": 1.0,
            "rank": 1,
        }
    ] if cite_law else []
    yield ToolChunk(type="meta", payload={
        "query_type": "direct_article" if is_direct_article_query else "semantic",
        "selected_source": selected_source or "pg",
        "selected_articles": selected_articles,
        "citations": pg_citations,
        "fallback_used": False,
        "confidence_score": None,
        "tool": "law_rag_tool",
    })
    yield ToolChunk(type="status", payload="🧠 GPT 요약 중...")

    # ✅ 포맷 분기
    if is_direct_article_query:
        prompt = f"""사용자 질문: "{query}"
아래 조문을 기반으로 법의 취지와 목적을 설명해.
⚠️ 시행일자나 출처는 출력하지 마 (별도로 추가됨).

출력 형식:
🔹 **법 설명** (법의 취지를 한 문단으로 요약)

[조문 전문]
{text_val}"""
    else:
        prompt = f"""사용자 질문: "{query}"
아래 조문을 참고해 질문 의도에 맞게 실무 중심으로 답변해.

출력 형식:
🔹 **결론** (조문이 "대통령령으로 정한다"·"별표 N과 같다"처럼 다른 규정에 맡기면 수치·인원은 그 규정(시행령·별표)에
  있다고 밝히고 제공된 조문만으로 숫자를 단정하지 않는다 — 별표는 이 DB에 없다.)
🔹 **판단 근거** (상황 조건 및 적용 요건)
🔹 **법적 근거**
  - [법령명] 제X조 제X항: (조문 내용)
🔹 **적용 방법** (제공된 조문에 명시된 사항만 정리 — 조문에 없는 일반적 안전관리 조언은 쓰지 마)
🔹 **출처** (법령명 + 조문번호)

[조문 전문]
{text_val}"""

    try:
        stream = await settings.openai_client.chat.completions.create(
            model=settings.LLM_MODEL,
            timeout=settings.GPT_TIMEOUT_SECONDS,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _prepend_context(context, prompt)},
            ],
            temperature=0.2,
            stream=True,
        )

        summary_parts = []
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                summary_parts.append(delta)
                # ✅ 스트리밍 중간에도 바로 전송
                yield ToolChunk(type="text", payload=delta)
        
        # ✅ 스트림 끝나면 전체 텍스트 조합
        summary = "".join(summary_parts).strip()
        law_url = f"https://www.law.go.kr/법령/{urllib.parse.quote(cite_law)}" + (
            f"/{article_display(cite_art)}" if cite_art else ""
        )

        # ✅ 출력 포맷 (Markdown 하이퍼링크 적용)
        if is_direct_article_query:
            # ⚙️ 스트리밍 중에는 이미 본문을 보냈으므로
            # 여기서는 법령 정보(시행일자, 출처)만 추가 출력
            footer = (
                f"\n\n📘 **법령 정보**  \n"
                f"시행일자: {enforcement_date or '정보 없음'}{enforcement_notice(enforcement_date)}  \n"
                f"출처: [{cite_law} {article_display(cite_art)}]({law_url})"
            )
            yield ToolChunk(type="text", payload=footer)
        else:
            # summary는 스트리밍으로 이미 전송됨 → 조문 원문 + 시행일자만 추가
            footer = f"\n\n**시행일자:** {enforcement_date or '정보 없음'}{enforcement_notice(enforcement_date)}"
            yield ToolChunk(type="text", payload=footer)

        # ✅ 마지막에 출처 정보만 별도로 전송
        yield ToolChunk(type="source", payload={
            "retrieved_laws": pg_citations,
            "law_url": law_url,
        })

    except Exception as e:
        print(f"⚠️ GPT 요약 실패: {e}")
        yield ToolChunk(type="error", payload="❌ 답변 생성 중 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")

    yield ToolChunk(type="status", payload="✅ 법령 검색 완료")

