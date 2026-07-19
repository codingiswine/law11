#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fault_inject.py — 장애 주입 관찰 스크립트
─────────────────────────────────────────────
의존성을 하나씩 죽인 상태에서 경로별 대표 질문을 던져 사용자가 실제로
보는 응답(내용·에러 처리·행 여부·소요 시간)을 기록한다. README #31의 근거.

실행 순서 (백엔드는 localhost:8000에 로컬 uvicorn으로 띄운 상태에서):
    python -m eval.fault_inject "0-베이스라인"
    docker stop qdrant   && python -m eval.fault_inject "A-Qdrant 다운"   && docker start qdrant
    docker stop postgres && python -m eval.fault_inject "B-PG 다운"      && docker start postgres
    # C/D/E: 환경변수를 무효 키로 바꿔 uvicorn 재시작 후 실행
    #   C: OPENAI_API_KEY=sk-invalid  D: TAVILY_API_KEY=invalid
    #   E: TAVILY_API_KEY/NAVER_CLIENT_ID/NAVER_CLIENT_SECRET 모두 invalid

기대 동작 (2026-07-19 수정 후):
    A: PG 무영향, 벡터 경로는 웹 폴백 전환 (행 없음)
    B: 직접 조회는 Qdrant 대체 정확 조회로 답변, "존재하지 않습니다" 오보 금지
    C: 정화된 일반 에러 메시지(원문 미노출), 빈 답변 저장 스킵(saved 이벤트 없음)
    E: 근거 없는 수치 생성 금지 — "확인할 수 없습니다" 정직 안내
"""
import asyncio
import json
import sys
import time
import uuid

import httpx

API = "http://localhost:8000/api/ask"
QUESTIONS = [
    ("PG정확매칭", "산업안전보건법 제17조 내용은?"),
    ("벡터검색",   "안전관리자 선임 기준은?"),
    ("웹fallback", "수영장 안전성 평가는 어떻게 해?"),
]
TIMEOUT = 45.0


async def probe(client, label, q):
    start = time.monotonic()
    events = []
    text_parts = []
    error_payloads = []
    status_code = None
    hang = False
    try:
        async with client.stream(
            "POST", API,
            json={"user_id": "faulttest", "question": q, "session_id": f"fault-{uuid.uuid4()}"},
            timeout=TIMEOUT,
        ) as resp:
            status_code = resp.status_code
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    m = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                ev = m.get("event")
                events.append(ev)
                if ev == "text":
                    text_parts.append(m["payload"])
                elif ev == "error":
                    error_payloads.append(str(m["payload"])[:90])
    except httpx.TimeoutException:
        hang = True
    except Exception as e:
        error_payloads.append(f"{type(e).__name__}: {e}"[:90])
    elapsed = time.monotonic() - start

    answer = "".join(text_parts).replace("\n", " ")
    from collections import Counter
    ev_summary = dict(Counter(events))
    print(f"  [{label}] HTTP={status_code} {elapsed:.1f}s hang={hang}")
    print(f"    events={ev_summary}")
    if error_payloads:
        print(f"    errors={error_payloads[:2]}")
    print(f"    answer[:110]={answer[:110] or '(없음)'}")


async def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "?"
    print(f"\n===== 시나리오: {scenario} =====")
    async with httpx.AsyncClient() as client:
        for label, q in QUESTIONS:
            await probe(client, label, q)


if __name__ == "__main__":
    asyncio.run(main())
