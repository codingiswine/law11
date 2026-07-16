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
from app.services.question_router import _DB_KEYWORDS
try:
    from app.config import settings   # ✅ Docker 실행 시
except ModuleNotFoundError:
    from app.config import settings  # ✅ 로컬 실행 시



# --------------------------
# DB 직접 조회 (chat_history — 이전 대화 기록)
# --------------------------
# ⚠️ 라우터 트리거("기록에서" 등)만 지우면 "확인해줘" 같은 요청동사가 남아
# 여전히 전체 문자열 매치에 실패한다 (실측: "비계 기록에서 확인해줘" →
# "확인해줘"가 붙은 채로 남아 "비계 설치 안전 기준 알려줘"와 매치 안 됨).
# 검색 의도가 없는 흔한 요청동사도 함께 제거해야 실제 주제어만 남는다.
_REQUEST_VERBS = ["확인해줘", "확인해주세요", "알려줘", "알려주세요", "찾아줘", "찾아주세요", "보여줘", "보여주세요"]


def _extract_search_term(query: str) -> str:
    """라우터 트리거 문구("기록에서"/"db에서" 등)와 흔한 요청동사를 질문에서
    제거하고 남은 부분을 검색어로 쓴다."""
    term = query
    for kw in _DB_KEYWORDS + _REQUEST_VERBS:
        term = term.replace(kw, "")
    return term.strip()


_RECENT_HISTORY_SQL = text("""
    SELECT u.content AS question, a.content AS answer, u.created_at
    FROM chat_history u
    JOIN chat_history a
      ON a.session_id = u.session_id AND a.turn_index = u.turn_index + 1 AND a.role = 'assistant'
    WHERE u.role = 'user'
    ORDER BY u.created_at DESC
    LIMIT 5
""")

_KEYWORD_SEARCH_SQL = text("""
    SELECT u.content AS question, a.content AS answer, u.created_at
    FROM chat_history u
    JOIN chat_history a
      ON a.session_id = u.session_id AND a.turn_index = u.turn_index + 1 AND a.role = 'assistant'
    WHERE u.role = 'user' AND u.content ILIKE :kw
    ORDER BY u.created_at DESC
    LIMIT 5
""")


async def run_db_query_tool(query: str) -> List[Dict]:
    """PostgreSQL chat_history에서 이전 대화 기록 검색 (비동기).

    chat_history는 user/assistant 메시지를 별도 행(role, content)으로 저장하고
    같은 session_id 내에서 turn_index, turn_index+1로 짝을 이룬다 (routes.py의
    save_chat_history 참고) — user_query/assistant_answer라는 별도 컬럼이나
    law_test 테이블은 존재하지 않는다.

    ⚠️ "다시 말해줘"/"그거 뭐였지" 같은 자연어 재확인 요청은 _extract_search_term이
    아무리 트리거/요청동사를 늘려도 다 못 걸러낸다 (실측: "그거가 정확히
    뭐였는지 다시 말해줘"는 "말해줘"가 목록에 없어 문장 전체가 그대로 남아
    과거 메시지와 매치될 수 없었음). 특정 문구를 계속 추가하는 대신, 키워드
    검색이 실제로 0건이면 최근 대화를 그대로 보여주는 폴백으로 일반화한다.
    """
    search_term = _extract_search_term(query)

    try:
        async with settings.async_engine.connect() as conn:
            if search_term:
                rows = await conn.execute(_KEYWORD_SEARCH_SQL, {"kw": f"%{search_term}%"})
                results = rows.fetchall()
                if results:
                    return [dict(r._mapping) for r in results]

            rows = await conn.execute(_RECENT_HISTORY_SQL)
            return [dict(r._mapping) for r in rows.fetchall()]
    except Exception as e:
        print(f"❌ [DB] 쿼리 실행 실패: {e}")
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
