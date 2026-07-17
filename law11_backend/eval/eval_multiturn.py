#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_multiturn.py — 멀티턴 회귀 eval
─────────────────────────────────────────────────────────────
실제로 발견해서 고쳤던 멀티턴 버그들을 2턴 시나리오로 박제한다.
각 케이스는 해당 fix 커밋의 라이브 재현 시나리오 그대로다.
골든 데이터셋(단일턴 RAGAS)이 구조적으로 못 잡는 버그 클래스 전용.

사용법:
    백엔드가 localhost:8000 에 떠 있어야 한다 (PG/Qdrant 포함).
    cd law11_backend
    python -m eval.eval_multiturn

판정:
    - expect_any: 마지막 턴 답변에 키워드 중 하나라도 포함돼야 통과
      (이전 턴의 주제를 이어받았는지 확인)
    - expect_tool / forbid_tool: 마지막 턴이 chat_history metadata->>'tool'에
      기록한 단축 tool 이름 검사 (라우팅 회귀 확인)
    하나라도 실패하면 exit 1 (CI 연동용).
"""

import sys
import json
import asyncio
import uuid
from pathlib import Path

import httpx
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings

API_URL = "http://localhost:8000/api/ask"

# ── 시나리오: 전부 실제 fix 커밋의 재현 케이스 ──────────────────
SCENARIOS = [
    {
        "id": "MT-001",
        "bug": "v1.3.2 (236fb8e) db_query_tool_async가 자연어 재확인 요청에서 결과를 못 찾음",
        "turns": [
            "산업안전보건법상 비계 설치 안전 기준 알려줘",
            "그거가 정확히 뭐였는지 다시 말해줘",
        ],
        "expect_any": ["비계"],
    },
    {
        "id": "MT-002",
        "bug": "v1.3.1 (f651033) general_tool이 이전 대화 context를 안 읽음",
        "turns": [
            "산업안전보건법상 비계 설치 안전 기준 알려줘",
            "휴... 그거 다 지키려니까 너무 힘들다",
        ],
        "expect_any": ["비계"],
    },
    {
        "id": "MT-003",
        "bug": "(3634f51) websearch_tool이 후속 질문에서 context를 무시하고 엉뚱한 답",
        "turns": [
            "비계 설치 안전 기준 알려줘",
            "그거 안 지키면 처벌은 어떻게 돼?",
        ],
        "expect_any": ["비계"],
    },
    {
        "id": "MT-004",
        "bug": "(69c2320) '최근 거'가 법령 키워드 '근거'로 오탐돼 후속질문이 law로 오라우팅",
        "turns": [
            "안전모 관련 사고 뉴스 있어?",
            "그 중에 제일 최근 거 자세히 알려줘",
        ],
        "forbid_tool": "law",
    },
    {
        "id": "MT-005",
        "bug": "(65d48ce) 세션 히스토리가 키워드 매칭에 번져 뉴스 질문이 law로 오라우팅",
        "turns": [
            "산업안전보건법 제38조 내용 알려줘",
            "계단 관련 사고 뉴스 찾아봐",
        ],
        "expect_tool": "news",
    },
]


async def ask(client: httpx.AsyncClient, session_id: str, question: str) -> str:
    """SSE 스트림을 끝까지 읽어 text 청크만 이어붙인 답변 반환."""
    parts = []
    async with client.stream(
        "POST", API_URL,
        json={"user_id": "eval_multiturn", "question": question, "session_id": session_id},
        timeout=120.0,
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            try:
                msg = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if msg.get("event") == "text":
                parts.append(msg["payload"])
    return "".join(parts)


async def last_tool(session_id: str) -> str:
    """세션 마지막 assistant 턴에 기록된 단축 tool 이름 (예: law/news/db/general/websearch)."""
    sql = text("""
        SELECT metadata->>'tool' FROM chat_history
        WHERE session_id = :sid AND role = 'assistant'
        ORDER BY id DESC LIMIT 1
    """)
    async with settings.async_engine.connect() as conn:
        row = (await conn.execute(sql, {"sid": session_id})).fetchone()
    return row[0] if row and row[0] else ""


async def purge_eval_sessions() -> None:
    """이전 실행이 남긴 eval 세션 제거.

    db_query_tool_async의 키워드 검색은 세션 필터 없이 전역이라, 과거 eval
    실행이 남긴 동일 질문 행("그거가 정확히 뭐였는지 다시 말해줘")이 그대로
    매치돼 MT-001이 영원히 통과하는 오염이 생긴다 (revert 검증에서 실측).
    """
    sql = text("DELETE FROM chat_history WHERE session_id LIKE 'eval-mt-%'")
    async with settings.async_engine.begin() as conn:
        await conn.execute(sql)


async def run_scenario(sc: dict) -> dict:
    session_id = f"eval-mt-{uuid.uuid4()}"
    answer = ""
    async with httpx.AsyncClient() as client:
        for q in sc["turns"]:
            answer = await ask(client, session_id, q)
            await asyncio.sleep(0.5)   # 턴 저장 완료 여유

    failures = []
    if "expect_any" in sc and not any(k in answer for k in sc["expect_any"]):
        failures.append(f"답변에 {sc['expect_any']} 중 아무것도 없음")
    if "expect_tool" in sc or "forbid_tool" in sc:
        tool = await last_tool(session_id)
        if sc.get("expect_tool") and tool != sc["expect_tool"]:
            failures.append(f"tool={tool!r} (기대: {sc['expect_tool']!r})")
        if sc.get("forbid_tool") and tool == sc["forbid_tool"]:
            failures.append(f"tool={tool!r} (금지된 라우팅)")

    return {"id": sc["id"], "bug": sc["bug"], "ok": not failures,
            "failures": failures, "answer_preview": answer[:120]}


async def main() -> None:
    print(f"\n  멀티턴 회귀 eval — {len(SCENARIOS)}개 시나리오\n")
    await purge_eval_sessions()
    results = []
    for sc in SCENARIOS:
        print(f"  [{sc['id']}] {sc['bug'][:60]}...")
        try:
            r = await run_scenario(sc)
        except Exception as e:
            r = {"id": sc["id"], "bug": sc["bug"], "ok": False,
                 "failures": [f"{type(e).__name__}: {e}"], "answer_preview": ""}
        icon = "✅" if r["ok"] else "❌"
        print(f"        {icon} {'PASS' if r['ok'] else '; '.join(r['failures'])}")
        results.append(r)

    passed = sum(1 for r in results if r["ok"])
    print(f"\n  결과: {passed}/{len(results)} 통과\n")
    for r in results:
        if not r["ok"]:
            print(f"  ❌ {r['id']}: {'; '.join(r['failures'])}")
            print(f"     답변 미리보기: {r['answer_preview']}")
    if passed < len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
