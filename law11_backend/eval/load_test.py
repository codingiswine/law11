"""
동시 사용자 부하 테스트 — SSE 스트림을 끝까지 읽어 실제 응답 완료 시간을 측정.

배경: llex(law11의 전신) 시절 "재난안전관리팀 최대 10명 동시 사용"을 가정해
DB 커넥션 풀(pool_size=10)을 설정했지만, 실제 부하테스트는 한 적이 없었다.
이 스크립트로 그 가정을 검증한다.

사용법:
    source .venv/bin/activate
    cd law11_backend
    python -m eval.load_test --users 10
    python -m eval.load_test --users 20
"""

import argparse
import asyncio
import time
import uuid
from dataclasses import dataclass, field

import httpx

API_URL = "http://localhost:8000/api/ask"

# 직접 조문 조회 / 개념형 / 웹 폴백(DB 밖 법령) — 실제 사용 분포를 섞어서 구성
QUESTIONS = [
    "산업안전보건법 제17조 내용은?",
    "안전관리자 선임 기준은?",
    "중대재해 처벌 범위가 어떻게 돼?",
    "비계 설치 안전 기준 알려줘",
    "계단 안전성 평가는 어떻게 해?",
    "소방기본법 1조",
    "한 층에 소화기 몇 개 있어야돼?",
    "수영장 안전성 평가는 어떻게 해?",
    "중대재해처벌등에관한법률 제6조 내용",
    "재난 및 안전관리 기본법의 목적은?",
]


@dataclass
class Result:
    question: str
    ok: bool = False
    status_code: int | None = None
    error: str | None = None
    ttfb: float | None = None       # 첫 SSE 청크까지 걸린 시간
    total_time: float = 0.0
    chars: int = 0


async def ask_one(client: httpx.AsyncClient, question: str) -> Result:
    r = Result(question=question)
    start = time.monotonic()
    try:
        async with client.stream(
            "POST", API_URL,
            json={"user_id": "loadtest", "question": question, "session_id": str(uuid.uuid4())},
            timeout=60.0,
        ) as resp:
            r.status_code = resp.status_code
            if resp.status_code != 200:
                r.error = f"HTTP {resp.status_code}"
                return r
            async for chunk in resp.aiter_text():
                if r.ttfb is None:
                    r.ttfb = time.monotonic() - start
                r.chars += len(chunk)
            r.ok = True
    except Exception as e:
        r.error = f"{type(e).__name__}: {e}"
    finally:
        r.total_time = time.monotonic() - start
    return r


async def run_round(n_users: int, round_no: int) -> list[Result]:
    async with httpx.AsyncClient() as client:
        tasks = [
            ask_one(client, QUESTIONS[(round_no * n_users + i) % len(QUESTIONS)])
            for i in range(n_users)
        ]
        return await asyncio.gather(*tasks)


def summarize(label: str, results: list[Result]) -> None:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    print(f"\n=== {label}: {len(ok)}/{len(results)} 성공 ===")
    if failed:
        print("실패:")
        for r in failed:
            print(f"  - {r.question[:30]:<30} → {r.error}")
    if ok:
        ttfbs = sorted(r.ttfb for r in ok if r.ttfb is not None)
        totals = sorted(r.total_time for r in ok)
        def pct(arr, p):
            return arr[min(len(arr) - 1, int(len(arr) * p))]
        print(f"  TTFB   (첫 응답)  min={ttfbs[0]:.2f}s  p50={pct(ttfbs,0.5):.2f}s  p90={pct(ttfbs,0.9):.2f}s  max={ttfbs[-1]:.2f}s")
        print(f"  Total  (완료까지) min={totals[0]:.2f}s  p50={pct(totals,0.5):.2f}s  p90={pct(totals,0.9):.2f}s  max={totals[-1]:.2f}s")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=10, help="동시 사용자 수")
    parser.add_argument("--rounds", type=int, default=2, help="라운드 수 (각 라운드마다 --users명이 동시에 질문)")
    args = parser.parse_args()

    print(f"부하 테스트 시작: {args.users}명 동시 사용자 x {args.rounds}라운드 → {API_URL}")
    all_results: list[Result] = []
    for round_no in range(args.rounds):
        t0 = time.monotonic()
        results = await run_round(args.users, round_no)
        elapsed = time.monotonic() - t0
        summarize(f"Round {round_no + 1} ({args.users}명 동시, {elapsed:.2f}s 소요)", results)
        all_results.extend(results)

    summarize(f"전체 ({args.users}명 x {args.rounds}라운드)", all_results)


if __name__ == "__main__":
    asyncio.run(main())
