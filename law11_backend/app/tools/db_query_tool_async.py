#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_query_tool_async.py (v3.3, Stable Async)
────────────────────────────────────────────
- PostgreSQL + GPT Memory 통합 비동기 Tool
- run(plan) generator → FastAPI Stream 호환
"""

import asyncio
from sqlalchemy import text
from typing import List, Dict, AsyncGenerator
from core.stream import ToolChunk
try:
    from app.config import settings   # ✅ Docker 실행 시
except ModuleNotFoundError:
    from app.config import settings  # ✅ 로컬 실행 시



# --------------------------
# DB 직접 조회 (law_test / chat_history)
# --------------------------
async def run_db_query_tool(query: str) -> List[Dict]:
    """PostgreSQL에서 직접 질의 실행 (비동기)"""
    q = query.lower()
    if any(k in q for k in ["법", "조문", "시행령", "규칙"]):
        sql = text("""
            SELECT law_name, article_number, article_title, text
            FROM law_test
            WHERE text ILIKE :kw OR law_name ILIKE :kw
            LIMIT 5
        """)
    else:
        sql = text("""
            SELECT user_query, assistant_answer, created_at
            FROM chat_history
            WHERE user_query ILIKE :kw
            ORDER BY created_at DESC
            LIMIT 5
        """)

    try:
        async with settings.async_engine.connect() as conn:
            rows = await conn.execute(sql, {"kw": f"%{query}%"})
            results = rows.fetchall()
            return [dict(r._mapping) for r in results]
    except Exception as e:
        print(f"❌ [DB] 쿼리 실행 실패: {e}")
        return []


# --------------------------
# Memory: 최근 대화 불러오기
# --------------------------
async def get_recent_history(user_id: str, limit: int = 10) -> List[Dict]:
    """최근 대화 기록 불러오기 (Memory)"""
    sql = text("""
        SELECT user_query, assistant_answer
        FROM chat_history
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    try:
        async with settings.async_engine.connect() as conn:
            rows = await conn.execute(sql, {"user_id": user_id, "limit": limit})
            results = rows.fetchall()
            return list(reversed([
                {"question": r[0], "answer": r[1]} for r in results
            ]))
    except Exception as e:
        print(f"⚠️ [Memory] 대화 불러오기 실패: {e}")
        return []


# --------------------------
# 🧩 공통 진입점: run(plan)
# --------------------------
async def run(plan) -> AsyncGenerator[ToolChunk, None]:
    """
    FastAPI Stream에서 호출되는 비동기 엔트리포인트
    - plan.args를 통해 query를 가져옴
    - ToolChunk 객체를 yield하여 routes.py와 호환
    """
    query = plan.args.get("query", "")
    print(f"🔧 [DB Tool 실행] {query}")

    yield ToolChunk(type="status", payload=f"🧠 '{query}' 관련 DB 검색 중...")

    try:
        results = await run_db_query_tool(query)
    except Exception as e:
        yield ToolChunk(type="error", payload=f"⚠️ DB 쿼리 실행 중 오류: {str(e)}")
        return

    if not results:
        yield ToolChunk(type="text", payload="❌ DB에서 결과를 찾을 수 없습니다.")
        return

    for row in results:
        pretty = "\n".join([f"{k}: {v}" for k, v in row.items()])
        yield ToolChunk(type="text", payload=pretty)
        await asyncio.sleep(0)

    yield ToolChunk(type="status", payload=f"✅ 총 {len(results)}건의 결과 반환 완료")
