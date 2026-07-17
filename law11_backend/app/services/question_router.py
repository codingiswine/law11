import re
import unicodedata
from typing import Dict, Optional
from openai import AsyncOpenAI
from core.logger import law11_logger as logger
from sqlalchemy import text

from app.config import settings
from core.plan import ToolPlan

async_engine = settings.async_engine

_LLM_SYSTEM = """너는 Law11 법령 챗봇의 질문 라우터다.
사용자 질문을 보고 아래 도구 중 하나를 선택해.

도구 목록:
- law_rag_tool       : 한국 산업안전보건 법령 관련 (조문, 기준, 의무, 처벌 등)
- websearch_tool     : 외국 법령, 최신 개정, 법제처 외 웹 정보 필요
- news_tool          : 뉴스/기사/보도 요청
- blog_tool          : 블로그/후기/리뷰 요청
- general_tool       : 감정 대화, 일상 잡담, 법령과 무관한 질문
- db_query_tool_async: 이전 대화 기록 조회 요청

도구 이름만 출력해. 다른 설명은 금지."""

_llm_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
_llm_cache: Dict[str, str] = {}

# ── Fast-path 키워드
# ponytail: 단독 "근거"는 뺐다 — normalized_q가 공백을 제거하다 보니 "최근 거"가
# "최근거"로 붙어 "근거"를 오탐한다 (실측: "그 중에 제일 최근 거 자세히 알려줘"가
# LAW_RAG_TOOL로 잘못 라우팅됨). "법적근거"는 이미 별도 키워드로 있어 의도한
# 케이스는 그대로 커버되고, 단독 "근거"가 빠지면 그 문구만 LLM 분류로 넘어간다.
_LAW_KEYWORDS = ["법적근거", "법령", "법조문", "조문", "기준", "조항", "법률", "시행령", "시행규칙"]
_NEWS_KEYWORDS = ["뉴스", "보도", "이슈", "사건", "사고", "기사", "속보"]
_BLOG_KEYWORDS = ["블로그", "포스팅", "후기", "리뷰", "경험담"]
_DB_KEYWORDS = ["데이터에서", "기록에서", "db에서", "데이터 확인", "기록 확인"]
_FOREIGN_KEYWORDS = ["osha", "미국", "일본", "중국", "유럽", "eu", "iso", "ilo", "해외", "외국", "국제", "글로벌", "미국법", "일본법"]
_GENERAL_KEYWORDS = ["힘들", "피곤", "기분", "고마워", "감사", "사랑", "재밌", "화나", "짜증", "슬퍼", "걱정", "무서워", "불안", "외로워"]

# ✅ law_rag_tool.py의 article_match와 동일한 패턴 — "제17조"/"17조" 모두 매치.
# DB에 없는 법(예: 소방기본법)이어도 조문 번호가 있으면 law_rag_tool로 보내야
# 자체 웹 폴백(조문 인용 + 출처 포맷)을 타지, websearch_tool(뉴스/블로그 요약)로
# 새서 조문 인용 없는 답이 나오지 않는다.
# ponytail: "3조각으로 나눠줘"처럼 숫자+조가 우연히 다른 단어(조각/조언/조사 등)의
# 일부인 경우 오탐 가능 — "N조" 뒤에 조사(는/를/의 등)가 공백 없이 바로 붙는 게
# 정상 표현이라 한글 뒤이음 여부로는 구분 불가. 법령 챗봇 특성상 실사용 빈도가
# 낮아 감수. 늘어나면 조사 허용목록으로 좁히기.
_ARTICLE_NUMBER_PATTERN = re.compile(r"(?:제)?\s*\d+\s*조")

_raw_laws = [
    "산업안전보건법", "산업안전보건법 시행령", "산업안전보건법 시행규칙",
    "산업안전보건기준에 관한 규칙", "재난 및 안전관리 기본법",
    "재난 및 안전관리 기본법 시행령", "재난 및 안전관리 기본법 시행규칙",
    "중대재해 처벌 등에 관한 법률", "중대재해 처벌 등에 관한 법률 시행령",
]
_CORE_LAWS = [unicodedata.normalize("NFC", law.replace(" ", "")) for law in _raw_laws]


async def _load_session_context(session_id: str, limit: int = 5) -> str:
    if not session_id:
        return ""
    sql = text("""
        SELECT role, content FROM chat_history
        WHERE session_id = :session_id
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(sql, {"session_id": session_id, "limit": limit * 2})
            rows = list(reversed(result.fetchall()))
        return "\n".join(
            f"{'사용자' if row.role == 'user' else 'Law11'}: {row.content}" for row in rows
        )
    except Exception as e:
        logger.warning(f"⚠️ [Router] 세션 컨텍스트 로딩 실패: {e}")
        return ""


async def _classify_with_llm(question: str, history: str) -> str:
    cache_key = question.strip()
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    context = f"이전 대화:\n{history}\n\n질문: {question}" if history.strip() else question
    try:
        resp = await _llm_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": _LLM_SYSTEM}, {"role": "user", "content": context}],
            temperature=0,
            max_tokens=10,
        )
        tool = resp.choices[0].message.content.strip().lower().split()[0]
        valid = {"law_rag_tool", "websearch_tool", "news_tool", "blog_tool", "general_tool", "db_query_tool_async"}
        result = tool if tool in valid else "law_rag_tool"
        _llm_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning(f"⚠️ [Router] LLM 분류 오류 → 기본값 law_rag_tool: {e}")
        return "law_rag_tool"


async def detect_tool(user_id: str, text: str, session_id: Optional[str] = None) -> ToolPlan:
    history      = await _load_session_context(session_id) if session_id else ""
    # ⚠️ 반드시 "현재 질문"만으로 정규화한다. history를 섞으면 이전 답변에 있던
    # "기준"/"법적 근거" 같은 문구 때문에 이후 모든 메시지가 LAW_RAG_TOOL로
    # 오분류된다 (실측: "계단 관련 사고 뉴스 찾아봐"가 이전 턴의 법령 답변
    # 때문에 법령 키워드로 잘못 매치됨). history는 LLM 분류(_classify_with_llm)와
    # tool 실행 컨텍스트(ToolPlan.args["context"])에서만 별도로 사용한다.
    normalized_q = unicodedata.normalize("NFC", text.lower().replace(" ", ""))
    raw_q_lower  = text.lower()

    def _plan(tool: str) -> ToolPlan:
        return ToolPlan(tool=tool, args={"query": text, "context": history})

    if any(k in raw_q_lower for k in _FOREIGN_KEYWORDS):
        logger.info("🌐 [Router] 외국 법령/기관 → WEBSEARCH_TOOL (fast)")
        return _plan("websearch_tool")

    if _ARTICLE_NUMBER_PATTERN.search(text):
        logger.info("📜 [Router] 조문 번호 패턴 감지 → LAW_RAG_TOOL (fast)")
        return _plan("law_rag_tool")

    if any(k in normalized_q for k in _LAW_KEYWORDS):
        logger.info("🏛️ [Router] 법령 키워드 → LAW_RAG_TOOL (fast)")
        return _plan("law_rag_tool")

    if any(law in normalized_q for law in _CORE_LAWS):
        logger.info("🏛️ [Router] 법령명 감지 → LAW_RAG_TOOL (fast)")
        return _plan("law_rag_tool")

    if any(k in normalized_q for k in _NEWS_KEYWORDS):
        logger.info("🗞️ [Router] 뉴스 키워드 → NEWS_TOOL (fast)")
        return _plan("news_tool")

    if any(k in normalized_q for k in _BLOG_KEYWORDS):
        logger.info("📝 [Router] 블로그 키워드 → BLOG_TOOL (fast)")
        return _plan("blog_tool")

    if any(k in normalized_q for k in _DB_KEYWORDS):
        logger.info("💾 [Router] DB 키워드 → DB_QUERY_TOOL (fast)")
        return _plan("db_query_tool_async")

    if any(k in normalized_q for k in _GENERAL_KEYWORDS):
        logger.info("💬 [Router] 감정 키워드 → GENERAL_TOOL (fast)")
        return _plan("general_tool")

    logger.info("🤖 [Router] 애매한 질문 → LLM 분류 중...")
    tool = await _classify_with_llm(text, history)
    logger.info(f"🤖 [Router] LLM 결과 → {tool.upper()}")

    # ⚠️ LLM이 law_rag_tool을 고르면 그대로 보낸다. 예전에는 Qdrant top-1 score < 0.45
    # 면 websearch_tool로 강등하는 게이트가 있었지만, 실측 결과 점수가 질문의 법령
    # 여부와 분리되지 않았다 (진짜 법령 질문 "산재 은폐하면 어떻게 되나요?"=0.41 강등,
    # DB 밖 질문 "수영장 안전성 평가는?"=0.452 통과 — 어떤 threshold도 양쪽을 다 못
    # 맞춤). law_rag_tool 내부가 PG 정확 매칭 → Qdrant(자체 0.45/0.5 기준) → web
    # fallback(조문 인용 포맷, context 전달) 체인으로 같은 결정을 더 많은 정보로
    # 내리므로 거기에 위임한다.
    return _plan(tool)

