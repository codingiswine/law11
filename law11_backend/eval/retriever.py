#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retriever.py
─────────────────────────────────────────────────────────────
평가용 RAG 파이프라인 래퍼.

검색은 운영과 같은 함수(law_rag_tool.search_law_articles)를 그대로 호출하고,
GPT 답변만 직접 생성한다 (DB 이력 / LangChain Memory 사이드이펙트 없음).

단독 실행 시 연결 테스트:
    cd law11_backend
    source ../.venv/bin/activate
    python -m eval.retriever
"""

import sys
import asyncio
from pathlib import Path
from typing import List, Dict, Any

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.tools.law_rag_tool import (
    article_display,
    search_law_articles,   # 운영과 같은 계층형 검색 (PG → Qdrant → Web)
    SYSTEM_PROMPT,         # 운영과 같은 프롬프트로 평가한다 (#57)
)

openai_client = settings.openai_client

# 2026-10-19 이전에는 여기에 29자짜리 자체 프롬프트가 따로 있었다. 운영
# (law_rag_tool.SYSTEM_PROMPT, 1,281자 — 할루시네이션 방지 + 법 적용 3단계)과
# 다른 프롬프트로 채점하고 있었기 때문에, RAGAS 수치가 실제 답변 품질을
# 대변하지 못했다. 단일 소스로 통일한다 (#57).

# 2026-10-27 이전에는 검색 우선순위도 여기에 따로 구현돼 있었고, 운영과
# 30개 골든셋 중 3건에서 서로 다른 조문을 쓰고 있었다 — threshold 게이트
# 누락(GS-013·GS-027)과 법령명 인식 경로 누락(GS-026). search_law_articles
# 하나만 호출하도록 바꿔 검색 경로를 단일 소스로 통일한다.

# 운영 생성 온도와 동일하게 맞춘다 (law_rag_tool.py의 chat.completions 호출들)
GEN_TEMPERATURE = 0.2


async def retrieve_and_generate(question: str) -> Dict[str, Any]:
    """운영과 같은 경로로 검색 + GPT 답변 생성 후 RAGAS 평가용 딕셔너리 반환.

    Returns:
        {
            "question": str,
            "answer": str,
            "contexts": List[str],            # RAGAS용 조문 텍스트 리스트
            "retrieved_articles": List[str],  # ["산업안전보건법 제17조", ...]
            "source": str,                    # pg | qdrant | web | missing | db_error
        }

    ⚠️ source가 "web"/"missing"/"db_error"면 contexts가 비어 있다 — 운영이
    DB 조문 없이 답하는 경우라, RAGAS는 harness.compute_ragas에서 자동
    제외된다 (채점 대상은 조문 근거가 있는 케이스뿐). 제외된 건수는
    harness 리포트의 ragas_scored / web_fallback 항목으로 남는다.
    """
    found = await search_law_articles(question)

    contexts: List[str] = []
    retrieved_articles: List[str] = []
    for a in found.articles:
        text_val = (a.get("text") or "").strip()
        if not text_val:
            continue
        contexts.append(text_val)
        retrieved_articles.append(
            f"{a['law_name']} {article_display(a['article_number'])}" if a["article_number"] else a["law_name"]
        )

    if not contexts:
        return {
            "question": question,
            "answer": "관련 법령 조문을 찾을 수 없습니다.",
            "contexts": [],
            "retrieved_articles": [],
            "source": found.source,
        }

    out = await _generate(question, contexts, retrieved_articles)
    out["source"] = found.source
    return out


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
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=GEN_TEMPERATURE,
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

        print(f"검색 경로: {result['source']}")
        print(f"검색된 조문: {result['retrieved_articles']}")
        print(f"\n답변 (앞 300자):\n{result['answer'][:300]}")
        print(f"\ncontexts 수: {len(result['contexts'])}")

        if not result["contexts"]:
            print("\n⚠️  contexts가 비어있습니다. Qdrant 연결 및 데이터 적재를 확인하세요.")
        else:
            print("\n✅ retriever 정상 동작 확인")

    asyncio.run(_test())
