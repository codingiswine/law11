#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
case_law_rag_tool.py
────────────────────────────────────────────
판례(대법원 대상, 9개 추적 법령 인용분) 검색 tool.

law_rag_tool.py의 PG exact → Qdrant exact fallback → Qdrant semantic →
web fallback → GPT 요약 우선순위 체인과 anti-hallucination 원칙을
그대로 미러링하되, 판례의 평평한 식별 체계(사건번호 하나 — "N의M" 같은
가지조문 정규화가 필요 없음)에 맞춰 단순화했다.

⚠️ SYSTEM_PROMPT는 law_rag_tool.py의 SYSTEM_PROMPT(CLAUDE.md "수정 금지"
대상)와 별개다 — 절대 그쪽을 import/재사용하지 않는다.
"""

import re
from typing import Optional
from sqlalchemy import text
from qdrant_client.http.models import FieldCondition, MatchValue, Filter
from core.stream import ToolChunk
from app.tools.websearch_tool import summarize_web
from app.services.embedding_cache import get_embedding_async
from app.tools.law_rag_tool import detect_law_name, get_priority_law, expand_legal_terms
try:
    from app.config import settings   # ✅ Docker 실행 시
except ModuleNotFoundError:
    from app.config import settings   # ✅ 로컬 실행 시


# ─────────────────────────────
# 환경 설정
# ─────────────────────────────
qdrant = settings.qdrant_client
async_engine = settings.async_engine
COLLECTION = settings.QDRANT_CASE_LAW_COLLECTION_NAME


# ─────────────────────────────
# 공통 시스템 프롬프트 (law_rag_tool의 SYSTEM_PROMPT와 별개 — 재사용 금지)
# ─────────────────────────────
SYSTEM_PROMPT = """너는 대한민국 산업안전보건 판례 전문가 AI 어시스턴트다.
다음 규칙을 반드시 준수하여 판례 기반 답변을 생성한다.

[할루시네이션 방지 — 최우선 원칙]
- DB/Qdrant에서 판례가 제공된 경우: 반드시 해당 판례에 명시된 사건번호, 선고일자,
  법원명, 판시내용만 인용한다. 제공된 텍스트에 없는 형량, 배상액, 판단 근거를
  추론하거나 생성하지 않는다. 확인할 수 없는 내용은
  "해당 내용은 제공된 판례에서 확인되지 않습니다"라고 명시한다.
- Web fallback으로 판례가 제공된 경우: 웹 검색 결과의 사건번호/법원명을 출처와
  함께 제공한다. 검색 결과에 없는 내용을 임의로 추가하지 않는다.
- 어떤 경우에도 사건번호나 선고일자를 임의로 만들거나 다른 판례 내용과 혼용하지 않는다.

[판례 성격 안내 원칙]
과거 판례는 참고 정보일 뿐 동일한 사안에서 동일한 결과를 보장하지 않는다.
답변 말미에 이 점을 짧게 안내한다.

[답변 구성 원칙]
1. 결론 (판례가 어떤 판단을 내렸는지 한 문장 요약)
2. 사건 개요 (제공된 판시사항/판결요지 기반)
3. 판례 정보 (사건번호, 법원명, 선고일자)
4. 참고 안내 (동일 결과를 보장하지 않는다는 면책)

[금지 사항]
- 제공된 텍스트에 없는 형량·배상액·수치를 "일반적으로", "보통은" 등으로 포장해 추가하는 것 금지
- 사건번호·선고일자·법원명을 지어내는 것 금지
- 질문과 무관한 판례를 관련 있는 것처럼 인용하는 것 금지

[언어 규칙]
모든 설명은 반드시 존댓말(합쇼체)로 작성한다."""

WEB_SYSTEM_PROMPT = """너는 대한민국 판례 전문가 AI 어시스턴트다.
판례 데이터베이스에 해당 판례가 없어 웹 검색 결과를 바탕으로 답변한다.

[답변 원칙]
- 웹 검색 결과에서 확인된 사건번호와 법원명을 명시해 출처를 제시한다.
- 정확한 사건번호를 확인할 수 없는 경우 "(참고 기준)"임을 표시한다.
- 과거 판례는 참고 정보일 뿐 동일한 결과를 보장하지 않는다는 점을 안내한다.
- 모든 설명은 존댓말(합쇼체)로 작성한다.

[금지 사항]
- 근거 없이 사건번호나 판결 내용을 임의로 생성하는 것 금지
- "일반적으로", "보통은" 등으로 포장해 확인되지 않은 내용을 추가하는 것 금지"""


# ─────────────────────────────
# 유틸 함수
# ─────────────────────────────
def normalize_case_number(case_number: str) -> str:
    """사건번호 정규화 — 공백/전각만 제거. 조문과 달리 가지번호 스킴이 없다
    (사건번호는 "2024도5902"처럼 이미 그 자체로 유일한 평평한 식별자)."""
    import unicodedata
    s = unicodedata.normalize("NFC", case_number or "")
    return re.sub(r"\s", "", s)


# 사건번호 패턴: "연도(2~4자리) + 사건부호(한글 1글자) + 일련번호(2~6자리)"
# 예: 2024도5902, 2019다12345, 2022카확123
_CASE_NUMBER_PATTERN = re.compile(
    r"(\d{2,4}\s*(?:가|나|다|도|고|누|두|허|카|므|브|어)\s*\d{2,6})"
)


def detect_case_number(query: str) -> Optional[str]:
    """질문 내에서 사건번호 자동 감지."""
    m = _CASE_NUMBER_PATTERN.search(query)
    if not m:
        return None
    return re.sub(r"\s", "", m.group(1))


# ponytail: 법원명 감지 함수는 만들지 않는다 — 수집 범위가 대법원 판례만이라
# (case_law_updater_async.py의 SUPREME_COURT_CODE 필터) DB에 다른 법원 데이터가
# 없어 법원명으로 좁혀도 결과가 달라지지 않는다. 하급심을 수집하게 되면 추가.


def _prepend_context(context: str, content: str) -> str:
    if not context:
        return content
    return f"[이전 대화]\n{context}\n\n{content}"


def _case_source_line(case_name: str, case_number: str, court_name: str, judgment_date) -> str:
    return f"[{court_name} {case_number}] {case_name} (선고: {judgment_date or '정보 없음'})"


# ─────────────────────────────
# 핵심 실행 (Async)
# ─────────────────────────────
async def run(plan):
    query = plan.args.get("query", "")
    context = plan.args.get("context", "")
    yield ToolChunk(type="status", payload="📋 판례 검색 시작...")

    case_number = detect_case_number(query)
    is_direct_case_query = bool(case_number)

    text_val = None  # 판시사항+판결요지+전문 조합 (GPT 컨텍스트용)
    case_meta = None  # {case_name, case_number, court_name, judgment_date}
    selected_source: Optional[str] = None
    pg_error = False

    # ① 사건번호 직접 조회 (PostgreSQL 정확 매칭)
    if is_direct_case_query:
        search_norm = normalize_case_number(case_number)
        try:
            async with async_engine.connect() as conn:
                result = await conn.execute(
                    text("""
                        SELECT case_name, case_number, court_name, judgment_date,
                               holding_summary, ruling_gist, full_text
                        FROM case_law_chunks
                        WHERE case_number_norm = :num
                        LIMIT 1;
                    """),
                    {"num": search_norm}
                )
                row = result.fetchone()
                if row:
                    case_name, cnum, court_name, judgment_date, holding, gist, full = row
                    text_val = f"{holding}\n\n{gist}\n\n{full}".strip()
                    case_meta = {"case_name": case_name, "case_number": cnum, "court_name": court_name, "judgment_date": str(judgment_date) if judgment_date else None}
                    selected_source = "pg"
                    yield ToolChunk(type="status", payload="✅ [PostgreSQL] 판례 발견")
                else:
                    yield ToolChunk(type="status", payload="🔍 [Qdrant] 벡터 검색으로 전환...")
        except Exception as e:
            pg_error = True
            print(f"⚠️ [PostgreSQL] 판례 조회 실패: {e}")
            yield ToolChunk(type="status", payload="⚠️ [PostgreSQL] 오류 → 대체 경로 진행")

        # ② PG 인프라 에러 시 Qdrant 정확 필터 scroll()로 대체 조회
        # (README #31 교훈과 동일 원칙: 인프라 실패와 "존재 안 함"을 구분한다.
        # PG가 단순히 row를 못 찾은 경우엔 다른 사건을 대신 꺼내지 않는다.)
        if not text_val and pg_error:
            try:
                points, _ = await qdrant.scroll(
                    COLLECTION,
                    scroll_filter=Filter(must=[
                        FieldCondition(key="case_number", match=MatchValue(value=case_number)),
                    ]),
                    limit=1,
                    with_payload=True,
                )
                if points:
                    p = points[0].payload
                    text_val = f"{p.get('holding_summary', '')}\n\n{p.get('ruling_gist', '')}".strip()
                    case_meta = {
                        "case_name": p.get("case_name", ""), "case_number": p.get("case_number", ""),
                        "court_name": p.get("court_name", ""), "judgment_date": p.get("judgment_date"),
                    }
                    selected_source = "qdrant"
                    yield ToolChunk(type="status", payload="✅ [Qdrant] 대체 정확 조회 성공 (PG 장애)")
            except Exception as e2:
                print(f"⚠️ [Qdrant] 대체 조회도 실패: {e2}")
            if not text_val:
                yield ToolChunk(type="text", payload="일시적인 데이터베이스 오류로 판례를 조회하지 못했습니다. 잠시 후 다시 시도해 주시기 바랍니다.")
                yield ToolChunk(type="status", payload="⚠️ 조회 실패 (일시적 DB 오류)")
                return
        elif not text_val and not pg_error:
            # PG가 정상 응답했는데 단순히 없는 경우 — 다른 판례로 대체하지 않고 정직하게 안내
            yield ToolChunk(type="text", payload=f"**{case_number}** 판례는 데이터베이스에 존재하지 않습니다.\n\n사건번호를 확인해 주시거나, 수집 범위가 대법원 판례(9개 추적 법령 관련)로 한정되어 있음을 참고해 주십시오.")
            yield ToolChunk(type="status", payload="✅ 조회 완료 (판례 없음)")
            return

    # ③ 사건번호 없음 → Qdrant 의미검색 (주제 기반)
    citations = []
    if not text_val:
        yield ToolChunk(type="status", payload="🧠 [Qdrant] 판례 의미 검색 중...")
        try:
            priority_law = detect_law_name(query) or get_priority_law(query)
            embedding = await get_embedding_async(expand_legal_terms(query))
            q_filter = (
                Filter(must=[FieldCondition(key="source_law_norm", match=MatchValue(value=priority_law))])
                if priority_law else None
            )
            results = await qdrant.search(COLLECTION, embedding, query_filter=q_filter, limit=10, with_payload=True)
            if (not results or results[0].score < 0.45) and priority_law:
                results = await qdrant.search(COLLECTION, embedding, limit=10, with_payload=True)
            # 리랭킹 없음 — law_rag_tool의 cross-encoder 실험이 한국어에서 랭킹 악화로
            # 기각된 전적을 그대로 따름 (raw Qdrant 코사인 점수 순서 신뢰).
            results = results[:5]
            # ⚠️ threshold 0.45는 law_rag_tool Branch A 값을 초기값으로 가져온 것 —
            # 판례 텍스트가 조문보다 길고 노이즈가 많아 그대로 맞다는 보장이 없다.
            # eval/eval_retrieval.py로 판례 골든셋 확보 후 재검증 필요 (계획서 3번 섹션).
            if results and results[0].score >= 0.45:
                seen = set()
                deduped = []
                for r in results:
                    cnum = r.payload.get("case_number", "")
                    if cnum and cnum not in seen:
                        seen.add(cnum)
                        deduped.append(r)
                contexts = [
                    f"[{r.payload.get('court_name')} {r.payload.get('case_number')}] {r.payload.get('case_name')}\n"
                    f"{r.payload.get('holding_summary', '')}\n{r.payload.get('ruling_gist', '')}"
                    for r in deduped
                ]
                citations = [
                    {
                        "case_name": r.payload.get("case_name", ""),
                        "case_number": r.payload.get("case_number", ""),
                        "court_name": r.payload.get("court_name", ""),
                        "judgment_date": r.payload.get("judgment_date"),
                        "score": round(r.score, 4),
                        "rank": i,
                    }
                    for i, r in enumerate(deduped, start=1)
                ]
                text_val = "\n\n".join(contexts)
                selected_source = "qdrant"
                yield ToolChunk(type="status", payload=f"✅ [Qdrant] 관련 판례 {len(deduped)}건 발견")
        except Exception as e:
            print(f"⚠️ Qdrant 판례 검색 실패: {e}")
            yield ToolChunk(type="status", payload="⚠️ Qdrant 검색 실패 → 대체 경로 진행")

    # ④ Web fallback (판례 없음)
    if not text_val or not isinstance(text_val, str) or not text_val.strip():
        yield ToolChunk(type="status", payload="⚠️ 관련 판례 없음 → Web 검색으로 보완")
        web_result = await summarize_web(f"{query} 판례", context=context)
        # ⚠️ 검색 결과가 하나도 없으면 GPT 생성 자체를 중단한다. law_rag_tool.py와
        # 동일한 anti-hallucination 게이트 (README #31 교훈) — 완화하지 않음.
        if not web_result.get("raw_results"):
            yield ToolChunk(type="text", payload="현재 웹 검색이 일시적으로 불가하여 관련 판례를 확인할 수 없습니다. 잠시 후 다시 시도해 주시기 바랍니다.")
            yield ToolChunk(type="status", payload="⚠️ 웹 검색 결과 없음 — 근거 없는 답변 생성 중단")
            return
        web_summary = web_result.get("summaries", "")
        resp = await settings.openai_client.chat.completions.create(
            model=settings.LLM_MODEL,
            timeout=settings.GPT_TIMEOUT_SECONDS,
            messages=[
                {"role": "system", "content": WEB_SYSTEM_PROMPT},
                {"role": "user", "content": _prepend_context(context, f"""질문: {query}

아래 검색 결과를 참고해 관련 판례의 사건번호와 법원명을 인용하여 답변해.

[검색 결과]
{web_summary}

출력 형식:
🔹 **결론** (판례가 어떤 판단을 내렸는지 한 문장 요약)
🔹 **사건 개요**
🔹 **판례 정보** (사건번호, 법원명 — (참고 기준) 표시 포함 가능)
🔹 **참고 안내** (과거 판례는 참고 정보일 뿐 동일한 결과를 보장하지 않음)""")},
            ],
            temperature=0.2,
        )
        answer = resp.choices[0].message.content.strip()
        yield ToolChunk(type="meta", payload={
            "query_type": "direct_case" if is_direct_case_query else "semantic",
            "selected_source": "web",
            "selected_articles": [],
            "fallback_used": True,
            "confidence_score": None,
            "tool": "case_law_rag_tool",
        })
        yield ToolChunk(type="text", payload=answer)
        yield ToolChunk(type="status", payload="✅ Web 보완 검색 완료")
        return

    # ⑤ 판례 발견 시 GPT 요약
    if is_direct_case_query and case_meta:
        citations = [{
            "case_name": case_meta["case_name"], "case_number": case_meta["case_number"],
            "court_name": case_meta["court_name"], "judgment_date": case_meta["judgment_date"],
            "score": 1.0, "rank": 1,
        }]

    yield ToolChunk(type="meta", payload={
        "query_type": "direct_case" if is_direct_case_query else "semantic",
        "selected_source": selected_source or "pg",
        "selected_articles": [_case_source_line(c["case_name"], c["case_number"], c["court_name"], c["judgment_date"]) for c in citations],
        "citations": citations,
        "fallback_used": False,
        "confidence_score": citations[0]["score"] if citations else None,
        "tool": "case_law_rag_tool",
    })
    yield ToolChunk(type="status", payload="🧠 GPT 요약 중...")

    if is_direct_case_query:
        # ⚠️ 사건번호/법원명/선고일자는 GPT에 만들게 하지 않는다 — law_rag_tool의
        # "시행일자는 DB 값만 표시 (GPT 생성 금지)" 원칙과 동일. text_val에는
        # 판시사항/판결요지/전문만 있고 이 메타필드가 없어, 요청하면 GPT가
        # "확인되지 않습니다"로 정직하게 답하거나 지어낼 위험이 있다 — 아래에서
        # DB 값을 footer로 직접 붙인다(⑥ 참고).
        prompt = f"""사용자 질문: "{query}"
아래 판례 내용을 기반으로 사건의 판단 내용을 설명해.
⚠️ 사건번호, 법원명, 선고일자는 출력하지 마 (별도로 추가됨).

출력 형식:
🔹 **결론** (판례가 어떤 판단을 내렸는지 한 문장 요약)
🔹 **사건 개요**
🔹 **참고 안내** (과거 판례는 참고 정보일 뿐 동일한 결과를 보장하지 않음)

[판례 내용]
{text_val}"""
    else:
        prompt = f"""사용자 질문: "{query}"
아래 관련 판례들을 참고해 질문 의도에 맞게 답변해.

출력 형식:
🔹 **결론**
🔹 **관련 판례**
  - [법원명 사건번호]: (판시 요지 핵심)
🔹 **참고 안내** (과거 판례는 참고 정보일 뿐 동일한 결과를 보장하지 않음)

[관련 판례]
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
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield ToolChunk(type="text", payload=delta)

        # ⑥ 사건번호/법원명/선고일자는 DB 값을 footer로 직접 붙인다 (GPT 생성 금지 —
        # law_rag_tool의 시행일자 처리와 동일 원칙).
        if is_direct_case_query and case_meta:
            footer = (
                f"\n\n📋 **판례 정보**  \n"
                f"사건번호: {case_meta['case_number']}  \n"
                f"법원명: {case_meta['court_name']}  \n"
                f"선고일자: {case_meta['judgment_date'] or '정보 없음'}"
            )
            yield ToolChunk(type="text", payload=footer)

        yield ToolChunk(type="source", payload={"retrieved_cases": citations})

    except Exception as e:
        print(f"⚠️ GPT 요약 실패: {e}")
        yield ToolChunk(type="error", payload="❌ 답변 생성 중 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")

    yield ToolChunk(type="status", payload="✅ 판례 검색 완료")
