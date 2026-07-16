#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
websearch_tool.py (v4.0, Tavily)
────────────────────────────────────────────
✅ 개선 요약
1️⃣ Google Custom Search → Tavily (Google은 2026년부로 신규 발급 중단, 기존 키도 2027-01-01 종료 예정)
2️⃣ 동시 호출 수를 세마포어로 제한 — 부하테스트에서 발견된 "동시 요청 몰릴 때 검색 API 429" 문제 예방
3️⃣ 결과 구조 유지 (summaries + raw_results)
"""

import aiohttp
import asyncio
from typing import List, Dict
try:
    from app.config import settings
    from core.stream import ToolChunk
except ModuleNotFoundError:
    from app.config import settings
    from core.stream import ToolChunk


# ponytail: 동시 웹 검색 호출 수 제한. 부하테스트(20명 동시)에서 Naver API가
# 초당 요청 제한(429)에 걸리는 걸 실측했음 — 공급자를 바꿔도 몰리면 똑같이
# 걸리는 문제라 호출 자체를 줄로 세워서 예방한다. 5는 임의값이라 실사용
# 트래픽 늘면 조정.
_SEARCH_SEMAPHORE = asyncio.Semaphore(5)


# --------------------------
# 🔍 비동기 Naver 검색
# --------------------------
async def naver_search(session, query: str, search_type: str = "news", display: int = 5) -> List[Dict]:
    if not settings.NAVER_CLIENT_ID or not settings.NAVER_CLIENT_SECRET:
        return []
    url = f"https://openapi.naver.com/v1/search/{search_type}.json"
    headers = {
        "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}

    try:
        async with _SEARCH_SEMAPHORE, session.get(url, headers=headers, params=params, timeout=20) as res:
            if res.status != 200:
                print(f"⚠️ Naver {search_type} HTTP {res.status}")
                return []
            data = await res.json()
            items = data.get("items", [])
            return [
                {
                    "title": i.get("title"),
                    "link": i.get("link"),
                    "snippet": i.get("description"),
                    "source": f"naver_{search_type}",
                }
                for i in items
            ]
    except Exception as e:
        print(f"⚠️ Naver {search_type} 검색 실패: {e}")
        return []


# --------------------------
# 🔍 비동기 Tavily 검색 (일반 웹 전체)
# --------------------------
async def tavily_search(session, query: str, max_results: int = 5) -> List[Dict]:
    if not settings.TAVILY_API_KEY:
        return []
    url = "https://api.tavily.com/search"
    headers = {"Authorization": f"Bearer {settings.TAVILY_API_KEY}"}
    payload = {"query": query, "max_results": max_results, "search_depth": "basic"}

    try:
        async with _SEARCH_SEMAPHORE, session.post(url, headers=headers, json=payload, timeout=20) as res:
            if res.status != 200:
                print(f"⚠️ Tavily HTTP {res.status}")
                return []
            data = await res.json()
            items = data.get("results", [])
            return [
                {
                    "title": i.get("title"),
                    "link": i.get("url"),
                    "snippet": i.get("content"),
                    "source": "tavily",
                }
                for i in items
            ]
    except Exception as e:
        print(f"⚠️ Tavily 검색 실패: {e}")
        return []


# --------------------------
# 🌐 통합 웹검색 (병렬)
# --------------------------
async def get_web_results(query: str) -> List[Dict]:
    """Tavily(일반 웹) + Naver 뉴스/블로그 비동기 병렬"""
    async with aiohttp.ClientSession() as session:
        naver_news, naver_blog, tavily_results = await asyncio.gather(
            naver_search(session, query, "news"),
            naver_search(session, query, "blog"),
            tavily_search(session, query),
        )
    all_results = tavily_results + naver_news + naver_blog

    # 중복 제거
    seen, unique_results = set(), []
    for r in all_results:
        link = r.get("link") or ""
        if link and link not in seen:
            unique_results.append(r)
            seen.add(link)
    return unique_results


# --------------------------
# 🧠 GPT 요약 (비동기)
# --------------------------
async def summarize_web(query: str, max_results: int = 8, context: str = "") -> Dict:
    """검색 결과를 GPT로 요약 (비동기, 법령 제외)

    ⚠️ 검색(get_web_results) 자체는 대화 이력 없이 현재 질문만으로 하되,
    요약 단계에서는 이전 대화(context)를 같이 줘야 "그거"/"그건" 같은
    지시어가 뭘 가리키는지 GPT가 알 수 있다. 실측: context 없이 "그거 안
    지키면 처벌은 어떻게 돼?"를 요약시켰더니 완전히 무관한 뉴스(Reddit 링크
    포함)를 답변으로 냈음.
    """
    if len(query) > 500:
        query = query[:500] + " ..."

    results = await get_web_results(query)
    results = results[:max_results]

    if not results:
        return {"summaries": "📰 관련 뉴스/블로그 검색 결과가 없습니다.", "raw_results": []}

    # 검색 결과 목록 (search_context) — 대화 이력(context)과는 별개
    search_context = "\n\n".join(
        [f"[{i+1}] {r['title']}\n{r['snippet']}\n{r['link']}" for i, r in enumerate(results)]
    )
    user_content = f"질문: {query}\n\n검색 결과:\n{search_context}"
    if context:
        user_content = f"[이전 대화]\n{context}\n\n{user_content}"

    messages = [
        {"role": "system", "content": (
            "너는 한국 뉴스·블로그 요약 전문가야.\n"
            "법조문 언급 없이 현실적인 뉴스·블로그 요약만 제시해.\n"
            "이전 대화가 주어지면 '그거'/'그건' 같은 지시어가 무엇을 가리키는지 이전 대화를 참고해서 파악해.\n"
            "[뉴스]\n1. 제목 / 핵심 요약\n[블로그]\n1. 작성자 / 주요 관점 요약"
        )},
        {"role": "user", "content": user_content}
    ]

    try:
        completion = await settings.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.4,
            max_tokens=700,
        )
        summary = completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ GPT 요약 실패: {e}")
        summary = "요약 중 오류가 발생했습니다."

    return {"summaries": summary, "raw_results": results}


# --------------------------
# 🔌 Tool 인터페이스 (routes.py에서 직접 호출)
# --------------------------
async def run(plan):
    """question_router → websearch_tool 직접 라우팅 시 호출되는 진입점"""
    query = plan.args.get("query", "")
    context = plan.args.get("context", "")
    yield ToolChunk(type="status", payload="🌐 웹 검색 중...")

    result = await summarize_web(query, context=context)
    summary = result.get("summaries", "")
    raw = result.get("raw_results", [])

    if not summary or "검색 결과가 없습니다" in summary:
        yield ToolChunk(type="text", payload="관련 웹 검색 결과를 찾지 못했습니다.")
        yield ToolChunk(type="status", payload="⚠️ 검색 결과 없음")
        return

    yield ToolChunk(type="text", payload=summary)

    if raw:
        sources = [r.get("link", "") for r in raw[:3] if r.get("link")]
        if sources:
            yield ToolChunk(type="source", payload={"web_urls": sources})

    yield ToolChunk(type="status", payload="✅ 웹 검색 완료")


# --------------------------
# 🧪 단독 테스트
# --------------------------
if __name__ == "__main__":
    async def _test():
        q = "소화기 설치 기준"
        result = await summarize_web(q)
        print("✅ 요약 결과:\n", result["summaries"])
        print("\n🧩 원문 링크:")
        for r in result["raw_results"]:
            print(f"- {r['title']} ({r['source']}) → {r['link']}")

    asyncio.run(_test())
