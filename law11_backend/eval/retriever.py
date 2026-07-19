#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retriever.py
─────────────────────────────────────────────────────────────
평가용 RAG 파이프라인 래퍼.

기존 rag_service의 임베딩·벡터 검색 함수를 재사용하되,
GPT 답변은 직접 호출 (DB 이력 / LangChain Memory 사이드이펙트 없음).

단독 실행 시 연결 테스트:
    cd law11_backend
    source .venv/bin/activate
    python -m eval.retriever
"""

import re
import sys
import asyncio
from pathlib import Path
from typing import List, Dict, Any

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text as sqltext

from app.config import settings
from app.services.rag_service import get_embedding_async, search_qdrant_async
from app.tools.law_rag_tool import (
    article_display,
    detect_law_name,
    get_priority_law,
    normalize_law_name,
)

openai_client = settings.openai_client

SYSTEM_PROMPT = (
    "너는 대한민국 산업안전보건 법령 전문 어시스턴트야. "
    "아래 법령 조문을 기반으로 질문에 정확하고 간결하게 답변해. "
    "제공된 조문 내용에만 근거해서 답변하고, 조문에 없는 내용은 추측하지 마."
)


async def retrieve_and_generate(
    question: str,
    limit: int = 5,
) -> Dict[str, Any]:
    """
    질문에 대해 Qdrant 검색 + GPT 답변 생성 후 RAGAS 평가용 딕셔너리 반환.

    Args:
        question: 사용자 질문
        limit: Qdrant 검색 결과 수 (default 5)

    Returns:
        {
            "question": str,
            "answer": str,
            "contexts": List[str],           # RAGAS용 조문 텍스트 리스트
            "retrieved_articles": List[str]  # ["산업안전보건법 제17조", ...]
        }
    """
    # ⚠️ 프로덕션(law_rag_tool)과 같은 검색 우선순위를 따른다 (v1.6.1):
    # ① 법령명+조문번호가 명시된 질문 → PostgreSQL 정확 매칭
    # ② 아니면 Qdrant 의미 검색 (조건 키워드가 법령을 암시하면 해당 법령 필터)
    # 예전에는 ①을 건너뛰고 순수 벡터만 측정해, direct_article 질문의 RAGAS
    # 수치가 사용자가 실제로 타는 경로를 반영하지 않았다.
    law_name = detect_law_name(question)
    m = re.search(r"(?:제)?\s*(\d+)\s*조(?:\s*의\s*(\d+))?", question)
    article_norm = ""
    if m:
        article_norm = m.group(1) + (f"의{m.group(2)}" if m.group(2) else "")

    if law_name and article_norm:
        sql = sqltext("""
            SELECT text FROM law_chunks
            WHERE law_name_norm = :law AND article_number_norm = :num LIMIT 1
        """)
        async with settings.async_engine.connect() as conn:
            row = (await conn.execute(
                sql, {"law": normalize_law_name(law_name), "num": article_norm}
            )).fetchone()
        if row:
            label = f"{law_name} {article_display(article_norm)}"
            return await _generate(question, [row[0].strip()], [label])

    # 임베딩 생성 (SQLite 캐시 활용) 후 Qdrant 의미 검색.
    # 프로덕션과 동일하게, 우선 법령 필터 결과가 부실하면(top score < 0.45)
    # 전체 법령으로 재검색한다.
    embedding = await get_embedding_async(question)
    priority_law = get_priority_law(question)
    qdrant_results = await search_qdrant_async(embedding, limit=limit, law_name_norm=priority_law)
    if priority_law and (not qdrant_results or qdrant_results[0]["score"] < 0.45):
        qdrant_results = await search_qdrant_async(embedding, limit=limit)

    contexts: List[str] = []
    retrieved_articles: List[str] = []

    for result in qdrant_results:
        payload = result.get("payload", {})
        r_law = payload.get("law_name", "")
        article_num = payload.get("article_number_norm", "")
        article_text = payload.get("text", "")

        if article_text.strip():
            contexts.append(article_text.strip())
            label = f"{r_law} {article_display(article_num)}" if article_num else r_law
            retrieved_articles.append(label)

    if not contexts:
        return {
            "question": question,
            "answer": "관련 법령 조문을 찾을 수 없습니다.",
            "contexts": [],
            "retrieved_articles": [],
        }

    return await _generate(question, contexts, retrieved_articles)


async def _generate(question: str, contexts: List[str], retrieved_articles: List[str]) -> Dict[str, Any]:
    """검색된 조문으로 GPT 답변 생성 (non-streaming, 결정론적)"""
    context_block = "\n\n".join(
        f"[{retrieved_articles[i]}]\n{ctx}"
        for i, ctx in enumerate(contexts)
    )

    user_message = (
        f"다음 법령 조문들을 참고하여 질문에 답변하세요.\n\n"
        f"법령 조문:\n{context_block}\n\n"
        f"질문: {question}\n\n"
        f"답변:"
    )

    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,
        max_tokens=800,
        stream=False,
    )

    answer = response.choices[0].message.content.strip()

    return {
        "question": question,
        "answer": answer,
        "contexts": contexts,
        "retrieved_articles": retrieved_articles,
    }


if __name__ == "__main__":
    async def _test():
        print("=== retriever 연결 테스트 ===\n")
        test_q = "안전관리자 선임 기준은 무엇인가요?"
        print(f"질문: {test_q}\n")

        result = await retrieve_and_generate(test_q)

        print(f"검색된 조문: {result['retrieved_articles']}")
        print(f"\n답변 (앞 300자):\n{result['answer'][:300]}")
        print(f"\ncontexts 수: {len(result['contexts'])}")

        if not result["contexts"]:
            print("\n⚠️  contexts가 비어있습니다. Qdrant 연결 및 데이터 적재를 확인하세요.")
        else:
            print("\n✅ retriever 정상 동작 확인")

    asyncio.run(_test())
