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
    """웹 fallback 답변 텍스트에서 [법령명] 제N조 패턴 추출"""
    citations = []
    seen = set()
    pattern = r'\[([^\]]{2,30}?)\]\s*제(\d+(?:의\d+)?)조'
    for rank, m in enumerate(re.finditer(pattern, answer), start=1):
        law_name, article = m.group(1).strip(), m.group(2)
        key = f"{law_name}:{article}"
        if key not in seen:
            seen.add(key)
            citations.append({"law_name": law_name, "article_number": article, "score": 0.0, "rank": rank})
        if len(citations) >= 5:
            break
    return citations
from datetime import datetime
from typing import Optional, Dict
from sqlalchemy import text
from qdrant_client.http.models import FieldCondition, MatchValue, Filter
from core.stream import ToolChunk
from app.tools.websearch_tool import summarize_web
from app.services.embedding_cache import get_embedding_async
from app.services import reranker
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
SYSTEM_PROMPT = """너는 대한민국 산업안전보건 법령 전문가 AI 어시스턴트다.
다음 규칙을 반드시 준수하여 법령 기반 답변을 생성한다.

[할루시네이션 방지 — 최우선 원칙]
- DB/Qdrant에서 조문이 제공된 경우: 반드시 해당 조문 텍스트에 명시된 내용만 인용한다.
  조문에 없는 수치(기간, 인원, 금액, 면적 등), 조건, 처벌 내용을 추론하거나 생성하지 않는다.
  확인할 수 없는 내용이 필요할 경우 "해당 내용은 제공된 조문에서 확인되지 않습니다"라고 명시한다.
- Web fallback으로 조문이 제공된 경우: 웹에서 검색된 법조문 내용을 출처와 함께 제공한다.
  이 경우에도 검색 결과에 없는 내용을 임의로 추가하지 않는다.
- 어떤 경우에도 조문 번호(제X조, 제X항)를 임의로 만들거나 다른 조문 내용과 혼용하지 않는다.

[법 적용 판단 우선 원칙]
모든 법령 인용은 다음 3단계 순서를 따른다.
1단계(사실 판단): 사용자 질문에서 위험 징후 또는 상황 조건을 먼저 파악한다.
2단계(적용 요건 판단): 해당 법 조문의 적용 요건이 충족되는지 판단한다.
3단계(법령 인용): 적용 요건이 충족되는 경우에만 해당 법 조문을 인용한다.
※ 단순히 '오래됨', '일반적 상황', '추상적 위험'만으로는 법을 적용하지 않는다.

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
1. 결론
2. 판단 근거 (사실 + 조건) — 제공된 조문 또는 웹 검색 결과에 명시된 내용만
3. 법령 인용 (조문 원문 기반)
4. 실제 적용 방법 또는 조치

[금지 사항]
- 조건 판단 없이 법령을 바로 인용하는 것 금지
- 조문에 없는 내용을 "일반적으로", "보통은" 등으로 포장해 추가하는 것 금지
- 설치 기준을 평가 기준처럼 사용하는 것 금지
- 질문 의도와 다른 방향으로 설명하는 것 금지

[언어 규칙]
법적 근거(조문 원문 인용) 외의 모든 설명은 반드시 존댓말(합쇼체)로 작성한다.

[핵심 원칙]
법령은 '많이 아는 것'이 아니라 '정확한 상황에서 올바르게 적용하는 것'이 중요하다.
DB 조문이 있으면 해당 조문만을 근거로, 웹 fallback 시에는 웹에서 가져온 법조문을 출처와 함께 제공한다."""

WEB_SYSTEM_PROMPT = """너는 대한민국 법령 전문가 AI 어시스턴트다.
법령 데이터베이스에 해당 조문이 없어 웹 검색 결과를 바탕으로 답변한다.

[답변 원칙]
- 웹 검색 결과에서 확인된 법령명과 조문 번호를 명시해 법적 근거를 제시한다.
- 정확한 조문 번호를 확인할 수 없는 경우 "(참고 기준)"임을 표시한다.
- 면적, 개수, 거리 등 수치 기준은 출처와 함께 제시한다.
- 실무자가 바로 적용할 수 있도록 구체적으로 작성한다.
- 모든 설명은 존댓말(합쇼체)로 작성한다.

[금지 사항]
- 근거 없이 수치나 조건을 임의로 생성하는 것 금지
- "일반적으로", "보통은" 등으로 포장해 확인되지 않은 내용을 추가하는 것 금지"""


# ─────────────────────────────
# 유틸 함수
# ─────────────────────────────
def normalize_law_name(name: str) -> str:
    import unicodedata
    return re.sub(r"[\s·]", "", unicodedata.normalize("NFC", name.strip()))

def normalize_article(article: str) -> str:
    return re.sub(r"[^\d]", "", article or "")

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
    ({"안전관리자", "보건관리자", "선임", "위탁", "관리감독자"},     "산업안전보건법"),
    ({"중대재해", "경영책임자", "처벌", "징역"},                     "중대재해처벌등에관한법률"),
    ({"재난", "대응", "복구", "위기관리"},                           "재난및안전관리기본법"),
]

def get_priority_law(query: str) -> Optional[str]:
    """키워드 조건에 따라 우선 검색할 법령_norm 반환. 없으면 None."""
    q = re.sub(r"\s+", "", query)
    for keywords, law_norm in _CONDITION_LAW_MAP:
        if any(k in q for k in keywords):
            return normalize_law_name(law_norm)
    return None


def _prepend_context(context: str, content: str) -> str:
    if not context:
        return content
    return f"[이전 대화]\n{context}\n\n{content}"


# ─────────────────────────────
# 핵심 실행 (Async)
# ─────────────────────────────
async def run(plan):
    query = plan.args.get("query", "")
    context = plan.args.get("context", "")
    yield ToolChunk(type="status", payload="⚖️ 법령 검색 시작...")

    law_name = detect_law_name(query)
    article_match = re.search(r"(?:제)?\s*(\d+)\s*조", query)
    article_number = article_match.group(1) if article_match else ""

    is_direct_article_query = bool(law_name and article_number)

    # ① 법령명 미인식 시 → 조건 기반 법령 우선 선택 후 Qdrant 검색
    if not law_name:
        # 키워드가 특정 법령을 암시하면 해당 법령으로 먼저 좁혀 검색한다.
        priority_law = get_priority_law(query)
        yield ToolChunk(type="status", payload="🧠 [Qdrant] 전체 법령 의미 검색 중...")
        try:
            embedding = await get_embedding_async(query)

            # 우선 법령이 있으면 해당 법령 내에서 먼저 검색, 없으면 전체 검색
            q_filter = (
                Filter(must=[FieldCondition(key="law_name_norm", match=MatchValue(value=priority_law))])
                if priority_law else None
            )
            results = await qdrant.search(
                COLLECTION,
                embedding,
                query_filter=q_filter,
                limit=10,
                with_payload=True
            )
            # 우선 법령 검색에서 결과가 부족하면 전체 재검색
            if (not results or results[0].score < 0.45) and priority_law:
                results = await qdrant.search(
                    COLLECTION,
                    embedding,
                    limit=10,
                    with_payload=True
                )
            # Re-ranking: 10개 → 상위 5개 선택
            if len(results) > 1:
                docs = [r.payload.get("text", "") for r in results]
                ranked_indices = reranker.rerank(query, docs, top_k=5)
                results = [results[i] for i in ranked_indices]
            # 0.45: 법령명 미인식 상태의 전체 검색이므로 넓게 허용.
            # 사용자가 법령 용어를 쓰지 않아도 관련 조문을 건질 수 있어야 한다.
            if results and results[0].score >= 0.45:
                # 중복 조문 제거 (Cross-Encoder 순서 기준으로 우선순위 결정)
                deduped = []
                seen_articles = set()
                for r in results:
                    text_val = r.payload.get("text", "")
                    r_law = r.payload.get("law_name", "")
                    r_article = r.payload.get("article_number_norm", "")
                    dedup_key = f"{r_law}:{r_article}"
                    if text_val and dedup_key not in seen_articles:
                        seen_articles.add(dedup_key)
                        deduped.append((r_law, r_article, text_val, r.score))

                # ✅ 화면에 표시되는 %(Qdrant 코사인 유사도)와 배지 순서가 일치하도록
                # 코사인 점수 내림차순으로 재정렬 (선택 자체는 위에서 Cross-Encoder로 이미 완료)
                deduped.sort(key=lambda x: x[3], reverse=True)

                contexts = [f"[{law} 제{art}조]\n{text}" for law, art, text, _ in deduped]
                sources = [f"{law} 제{art}조" for law, art, _, _ in deduped]
                citations = [
                    {"law_name": law, "article_number": art, "score": round(score, 4), "rank": rank}
                    for rank, (law, art, _, score) in enumerate(deduped, start=1)
                ]
                combined = "\n\n".join(contexts)
                yield ToolChunk(type="status", payload=f"✅ [Qdrant] 관련 조문 {len(contexts)}개 발견")
                yield ToolChunk(type="meta", payload={
                    "query_type": "semantic",
                    "selected_source": "qdrant",
                    "selected_articles": sources,
                    "citations": citations,
                    "fallback_used": False,
                    "confidence_score": deduped[0][3] if deduped else None,
                    "tool": "law_rag_tool",
                })

                prompt = f"""너는 대한민국 산업안전보건 법령 전문가야.
사용자 질문: "{query}"
아래 법령 조문을 반드시 인용하여 실무 중심으로 답변해.
⚠️ 법적 근거(조문 원문 인용) 외의 모든 설명은 반드시 존댓말(합쇼체)로 작성해.

출력 형식:
🔹 **결론** (한 문장 요약, 존댓말)
🔹 **법적 근거**
  - [법령명] 제X조 제X항: (조문 원문 또는 핵심 내용)
🔹 **적용 기준** (실무에서 지켜야 할 사항, 존댓말)

[관련 법령 조문]
{combined}"""

                stream = await settings.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
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

                yield ToolChunk(type="source", payload={"retrieved_laws": citations})
                yield ToolChunk(type="status", payload="✅ 법령 검색 완료")
                return
        except Exception as e:
            yield ToolChunk(type="status", payload=f"⚠️ Qdrant 검색 실패: {e}")

        # Qdrant에서 못 찾은 경우만 Web fallback
        yield ToolChunk(type="status", payload="⚠️ 관련 법령 없음 → Web 검색으로 보완")
        web_result = await summarize_web(query)
        web_summary = web_result.get("summaries", "")
        resp = await settings.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": WEB_SYSTEM_PROMPT},
                {"role": "user", "content": _prepend_context(context, f"""질문: {query}

아래 검색 결과를 참고해 반드시 구체적인 조문 번호(제X조 제X항)를 인용하여 답변해.
법령명만 나열하지 말고, 해당 조문이 무엇을 규정하는지 내용과 함께 명시해.

[검색 결과]
{web_summary}

출력 형식:
🔹 **결론** (한 문장 요약)
🔹 **판단 근거** (상황 조건 및 적용 요건)
🔹 **법적 근거**
  - [법령명] 제X조 제X항: (해당 조문이 규정하는 내용)
🔹 **적용 방법** (실무에서 지켜야 할 사항)
🔹 **출처** (법령명 + 조문번호)""")},
            ],
            temperature=0.2,
        )
        answer = resp.choices[0].message.content.strip()
        yield ToolChunk(type="meta", payload={
            "query_type": "semantic",
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
        return

    # ② PostgreSQL 검색 (1차: 정확한 조문 검색)
    text_val, enforcement_date = None, None
    selected_source: Optional[str] = None
    selected_articles: list = []
    search_law_norm = normalize_law_name(law_name)
    search_article_norm = normalize_article(article_number)

    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT text, enforcement_date
                    FROM law_chunks
                    WHERE law_name_norm = :law AND article_number_norm = :num
                    LIMIT 1;
                """),
                {"law": search_law_norm, "num": search_article_norm}
            )
            row = result.fetchone()
            if row:
                text_val, enforcement_date = row
                selected_source = "pg"
                selected_articles = [f"{law_name} 제{article_number}조"] if article_number else [law_name]
                yield ToolChunk(type="status", payload="✅ [PostgreSQL] 조문 발견")
            else:
                yield ToolChunk(type="status", payload="🔍 [Qdrant] 벡터 검색으로 전환...")
    except Exception as e:
        yield ToolChunk(type="status", payload=f"⚠️ [PostgreSQL] 오류 → Qdrant 검색: {e}")

    # ③ Qdrant (2차: 벡터 유사도 검색)
    # 단, 조문 번호가 명시된 직접 조회(is_direct_article_query)에서 PG miss는
    # "해당 조문 없음"을 의미 — Qdrant로 다른 조문을 대신 꺼내지 않는다.
    if not text_val and is_direct_article_query:
        msg = f"**{law_name} 제{article_number}조**는 데이터베이스에 존재하지 않습니다.\n\n조문 번호를 확인하시거나 법령명이 정확한지 검토해 주십시오."
        yield ToolChunk(type="text", payload=msg)
        yield ToolChunk(type="status", payload="✅ 조회 완료 (조문 없음)")
        return

    if not text_val:
        yield ToolChunk(type="status", payload="🧠 [Qdrant] 벡터 검색 중...")
        try:
            embedding = await get_embedding_async(query)
            q_filter = Filter(
                must=[
                    FieldCondition(key="law_name_norm", match=MatchValue(value=search_law_norm)),
                ]
            )
            results = await qdrant.search(
                COLLECTION,
                embedding,
                query_filter=q_filter,
                limit=10,
                with_payload=True
            )
            # Re-ranking: 10개 → 상위 5개 선택 후 best는 첫 번째
            if len(results) > 1:
                docs = [r.payload.get("text", "") for r in results]
                ranked_indices = reranker.rerank(query, docs, top_k=5)
                results = [results[i] for i in ranked_indices]
            # 0.50: 이미 법령명으로 범위를 좁혔는데 여기서도 미달이면
            # 해당 법령 DB에 답이 없다는 신호 → web fallback이 더 정확.
            # Case A(0.45)보다 엄격한 이유: 검색 범위가 좁을수록 낮은 score = 진짜 없음.
            # 주의: score는 reranking 후 cross-encoder top-1의 원본 Qdrant 코사인값임.
            if results and results[0].score >= 0.5:
                best = results[0]
                text_val = best.payload.get("text", "")
                enforcement_date = best.payload.get("enforcement_date", "")
                selected_source = "qdrant"
                r_law = best.payload.get("law_name", law_name)
                r_art = best.payload.get("article_number_norm", "")
                selected_articles = [f"{r_law} 제{r_art}조" if r_art else r_law]
                yield ToolChunk(type="status", payload=f"✅ [Qdrant] 유사도 {best.score:.2f} 조문 발견")
        except Exception as e:
            yield ToolChunk(type="status", payload=f"⚠️ Qdrant 검색 실패: {e}")

    # ④ Web fallback (모든 조문 검색 실패)
    if not text_val or not isinstance(text_val, str) or not text_val.strip():
        yield ToolChunk(type="status", payload="⚠️ 조문 없음 → Web fallback 실행")
        web_result = await summarize_web(query)
        web_summary = web_result.get("summaries", "")
        resp = await settings.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": WEB_SYSTEM_PROMPT},
                {"role": "user", "content": _prepend_context(context, f"""질문: {query}

아래 검색 결과를 참고해 반드시 구체적인 조문 번호(제X조 제X항)를 인용하여 답변해.
법령명만 나열하지 말고, 해당 조문이 무엇을 규정하는지 내용과 함께 명시해.

[검색 결과]
{web_summary}

출력 형식:
🔹 **결론** (한 문장 요약)
🔹 **판단 근거** (상황 조건 및 적용 요건)
🔹 **법적 근거**
  - [법령명] 제X조 제X항: (해당 조문이 규정하는 내용)
🔹 **적용 방법** (실무에서 지켜야 할 사항)
🔹 **출처** (법령명 + 조문번호)""")},
            ],
            temperature=0.2,
        )
        answer = resp.choices[0].message.content.strip()
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
        yield ToolChunk(type="status", payload="✅ Web fallback 완료")
        return

    # ⑤ 조문 발견 시 GPT 요약
    pg_citations = [
        {
            "law_name": law_name,
            "article_number": article_number,
            "score": 1.0,
            "rank": 1,
        }
    ] if law_name else []
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
🔹 **결론**
🔹 **판단 근거** (상황 조건 및 적용 요건)
🔹 **법적 근거**
  - [법령명] 제X조 제X항: (조문 내용)
🔹 **적용 방법** (실무에서 지켜야 할 사항)
🔹 **출처** (법령명 + 조문번호)

[조문 전문]
{text_val}"""

    try:
        stream = await settings.openai_client.chat.completions.create(
            model="gpt-4o-mini",
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
        law_url = f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}/제{article_number}조"

        # ✅ 출력 포맷 (Markdown 하이퍼링크 적용)
        if is_direct_article_query:
            # ⚙️ 스트리밍 중에는 이미 본문을 보냈으므로
            # 여기서는 법령 정보(시행일자, 출처)만 추가 출력
            footer = (
                f"\n\n📘 **법령 정보**  \n"
                f"시행일자: {enforcement_date or '정보 없음'}  \n"
                f"출처: [{law_name} 제{article_number}조]({law_url})"
            )
            yield ToolChunk(type="text", payload=footer)
        else:
            # summary는 스트리밍으로 이미 전송됨 → 조문 원문 + 시행일자만 추가
            footer = f"\n\n**시행일자:** {enforcement_date or '정보 없음'}"
            yield ToolChunk(type="text", payload=footer)

        # ✅ 마지막에 출처 정보만 별도로 전송
        yield ToolChunk(type="source", payload={
            "retrieved_laws": pg_citations,
            "law_url": law_url,
        })

    except Exception as e:
        yield ToolChunk(type="error", payload=f"❌ GPT 요약 실패: {e}")

    yield ToolChunk(type="status", payload="✅ 법령 검색 완료")

