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
    - forbid_any: 마지막 턴 답변에 키워드가 하나라도 있으면 실패 (#93)
    - expect_retrieved_any: 마지막 턴의 검색 조문(source 청크) 번호 중 하나라도 있어야 통과 (#96)
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
        # 원래 재현("그거 안 지키면 처벌은?")은 관련도 게이트 제거(v1.4.2) 후
        # law_rag_tool로 가게 되어 websearch context 경로를 안 지남. "해외"
        # fast-path 키워드로 websearch_tool 라우팅을 고정해 같은 fix를 박제.
        # 주의: turn 2에 주제어를 넣으면 GPT가 "그거"를 문장 안에서 해석해버려
        # context를 안 읽어도 답이 됨 (실측: "해외 산업안전 쪽에서는 그거..." →
        # '그거'='산업안전 규제'로 오해석). 지시어의 대상은 반드시 이전 턴에만
        # 존재해야 이 시나리오가 context 사용을 실제로 검증한다.
        "id": "MT-003",
        "bug": "(3634f51) websearch_tool이 후속 질문에서 context를 무시하고 엉뚱한 답",
        "turns": [
            "비계 설치 안전 기준 알려줘",
            "해외에서는 그거 어떻게 규제해?",
        ],
        "expect_any": ["비계"],
        "expect_tool": "websearch",
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
    {
        # 단일 턴이지만 "검색 누락 → 법령 전체 부정 단정" 회귀를 운영 경로로 잡는 자리가
        # 여기뿐이다. 정답(산소 18% 이상 23.5% 미만)은 제618조(정의)에 있다.
        "id": "MT-006",
        "bug": "(#93) 제618조가 top-5 밖이라 '적정공기 기준은 법령에 명시된 바 없다'고 단정",
        "turns": [
            "밀폐공간 작업 전 적정 공기 산소농도 기준이 뭐야?",
        ],
        "expect_any": ["18퍼센트", "18%", "18 퍼센트"],
        "forbid_any": ["명시된 바가 없", "명시된 바 없", "명시되어 있지 않", "법령에 없", "법령에서 정하고 있지 않"],
    },
    {
        # 인원 기준은 시행령 제16조가 별표 3에 맡기고 별표는 DB에 없다. #95에서는 "별표 참조"에서
        # 멈추는 것이 정답이었지만, #98부터 미확인은 웹으로 이어지므로 **보완 안내가 붙은 웹 답변**이
        # 정답이다 — 모델 지식의 "1명"을 조문 근거처럼 적는 것(수정 전 증상)과 구분되는 지점은 안내문.
        "id": "MT-007",
        "bug": "(#95→#98) 우선 법령 필터가 시행령을 빼고, 모델이 별표의 인원수를 지식으로 채움",
        "turns": [
            "상시근로자 300명인 제조업 사업장은 안전관리자를 몇 명 선임해야 해?",
        ],
        "expect_any": ["검색된 조문에 답이 없음", "별표"],
    },
    {
        # 지시어 후속 질문은 검색도 앞 턴을 알아야 한다 — 답변 텍스트가 아니라 **검색 조문**을 본다.
        "id": "MT-008",
        "bug": "(#96) 후속 질문을 현재 문장만으로 임베딩해 무관한 조문(53·184·125…)을 검색",
        "turns": [
            "밀폐공간 작업 전 적정 공기 산소농도 기준이 뭐야?",
            "그럼 그 측정은 누가 해야 해?",
        ],
        "expect_retrieved_any": ["619의2"],
    },
    {
        # 정답(제3조, 5명 미만 제외)이 벡터 15위 밖 — 모델이 미확인을 인정하면 거기서 멈추지 말고
        # 웹으로 보완해야 한다. 답에 보완 안내와 인원 기준이 둘 다 있어야 통과.
        "id": "MT-009",
        "bug": "(#98) 조문 5개에 답이 없어 '확인되지 않음'에서 멈추고 웹 폴백을 타지 않음",
        "turns": [
            "중대재해처벌법은 몇 명 이상 사업장부터 적용돼?",
        ],
        "expect_any": ["5명"],
        "forbid_any": ["확인되지 않습니다"],
    },
    {
        # 벌칙 조문(제168조)은 조문 번호 나열이라 벡터로 안 잡힌다 — 직전 턴이 인용한 규칙 조문에서
        # 법 제38조·제39조 벌칙을 코드로 꺼내 넣어야 한다. 질문에 사망 사실이 없으니 기본 벌칙이 결론.
        "id": "MT-010",
        "bug": "(#99) 후속 처벌 질문에 재난법 제78조의3(3년·3천만)을 가져다 씀 — 정답 산업안전보건법 제168조",
        "turns": [
            "비계 설치 안전 기준 알려줘",
            "그거 안 지키면 처벌은 어떻게 돼?",
        ],
        "expect_retrieved_any": ["168"],
        "expect_any": ["5년"],
        "forbid_any": ["3천만"],
    },
    {
        # 정의 조문(제618조)이 기준 0.45에 0.019 모자라 웹으로 샜던 질문 — DB 조문으로 답해야 한다.
        "id": "MT-011",
        "bug": "(#100) '산소결핍' 질문이 threshold 미달로 웹 폴백 → 제38조에 18%가 있다고 오귀속",
        "turns": [
            "밀폐공간에서 산소결핍이란 산소농도 몇 퍼센트 미만이야?",
        ],
        "expect_retrieved_any": ["618"],
        "expect_any": ["18퍼센트", "18%", "18 퍼센트"],
        "forbid_any": ["웹 검색"],
    },
]


async def ask(client: httpx.AsyncClient, session_id: str, question: str) -> tuple[str, list]:
    """SSE 스트림을 끝까지 읽어 (답변 텍스트, 검색 조문 번호 목록) 반환."""
    parts = []
    retrieved: list = []
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
            elif msg.get("event") == "source" and isinstance(msg.get("payload"), dict):
                retrieved = [a.get("article_number") for a in msg["payload"].get("retrieved_laws", [])]
    return "".join(parts), retrieved


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

    v1.7.2부터 db_query_tool_async가 session_id로 스코프되어 과거 eval 행이
    MT-001에 매치되는 오염(revert 검증에서 실측)은 구조적으로 불가능해졌지만,
    eval 행이 chat_history에 무한 누적되는 것을 막는 위생 + 필터 회귀 시
    방어선으로 유지한다.
    """
    sql = text("DELETE FROM chat_history WHERE session_id LIKE 'eval-mt-%'")
    async with settings.async_engine.begin() as conn:
        await conn.execute(sql)


async def run_scenario(sc: dict) -> dict:
    session_id = f"eval-mt-{uuid.uuid4()}"
    answer, retrieved = "", []
    async with httpx.AsyncClient() as client:
        for q in sc["turns"]:
            answer, retrieved = await ask(client, session_id, q)
            # 턴 저장 완료 여유 + 레이트리밋 간격: /api/ask는 IP당 10/분(#65)이라
            # 시나리오 6개(11턴)를 연달아 보내면 마지막 턴이 429로 끊긴다 (실측, #93).
            await asyncio.sleep(6.5)

    failures = []
    if "expect_any" in sc and not any(k in answer for k in sc["expect_any"]):
        failures.append(f"답변에 {sc['expect_any']} 중 아무것도 없음")
    hit = [k for k in sc.get("forbid_any", []) if k in answer]
    if hit:
        failures.append(f"답변에 금지 문구 {hit}")
    if "expect_retrieved_any" in sc and not any(k in retrieved for k in sc["expect_retrieved_any"]):
        failures.append(f"검색 조문 {retrieved}에 {sc['expect_retrieved_any']} 중 아무것도 없음")
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
