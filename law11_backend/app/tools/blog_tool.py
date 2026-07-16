#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blog_tool_v5.4_aiohttp (Law11 GPT-5 완전 비동기판)
────────────────────────────────────────────
✅ 주요 개선
1️⃣ requests → aiohttp 완전 비동기화
2️⃣ Google/Naver 블로그 동시 요청
3️⃣ ToolChunk 기반 스트리밍 유지
────────────────────────────────────────────
"""

import os, aiohttp, asyncio
from typing import List, Dict, AsyncGenerator
from urllib.parse import urlparse
from app.config import settings
from core.stream import ToolChunk
from app.tools._web_utils import strip_tags, unique_preserve_order


NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36"
)


# ─────────────────────────────
# 🔧 유틸 함수
# ─────────────────────────────
def brand_from_link(link: str) -> str:
    try:
        host = urlparse(link).netloc.lower()
        if "naver" in host: return "NAVER BLOG"
        if "tistory" in host: return "TISTORY"
        if "medium" in host: return "MEDIUM"
        if "blogspot" in host or "blogger" in host: return "BLOGGER"
        if "daum" in host: return "DAUM"
        parts = [p for p in host.split(".") if p not in {"www", "co", "kr", "com", "net"}]
        return parts[-1].upper() if parts else "BLOG"
    except:
        return "BLOG"


# ─────────────────────────────
# 🌐 네이버 블로그 (aiohttp)
# ─────────────────────────────
async def get_naver_blogs(session: aiohttp.ClientSession, query: str, max_results: int = 5) -> List[Dict[str, str]]:
    url = "https://openapi.naver.com/v1/search/blog.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID or "",
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET or "",
        "User-Agent": DEFAULT_UA,
    }
    params = {"query": query, "display": max_results, "sort": "sim"}

    async with session.get(url, headers=headers, params=params, timeout=8) as res:
        data = await res.json()
        blogs = []
        for i in data.get("items", []):
            blogs.append({
                "title": strip_tags(i.get("title")),
                "description": strip_tags(i.get("description")),
                "link": i.get("link", ""),
                "source": brand_from_link(i.get("link", "")),
            })
        return blogs


# ─────────────────────────────
# 🌍 구글 블로그 (Custom Search API, aiohttp)
# ─────────────────────────────
async def get_google_blogs(session: aiohttp.ClientSession, query: str, max_results: int = 5) -> List[Dict[str, str]]:
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return []
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": f"{query} site:blog.naver.com OR site:tistory.com OR site:medium.com OR site:blogspot.com",
        "num": max_results,
    }

    async with session.get(url, params=params, timeout=8) as res:
        data = await res.json()
        results = []
        for it in data.get("items", []):
            results.append({
                "title": strip_tags(it.get("title", "")),
                "description": strip_tags(it.get("snippet", "")),
                "link": it.get("link", ""),
                "source": brand_from_link(it.get("link", "")),
            })
        return results


# ─────────────────────────────
# 🧠 GPT 프롬프트
# ─────────────────────────────
def build_prompt(query: str, items: List[Dict[str, str]]) -> str:
    header = (
        f"'{query}' 관련 블로그 후기를 3건 요약하세요.\n"
        "출력 형식:\n"
        "1️⃣ 제목  \n"
        "출처 : 블로그명(링크)\n"
        "요약 (2~3줄, 자연스러운 문체)\n"
        "---\n\n"
        "주의:\n"
        "- 제목은 굵게 처리(**제목**)\n"
        "- Markdown 제목(#, ##) 사용 금지\n"
        "- 실제 후기처럼 자연스럽게 요약\n"
    )
    context = "\n".join([
        f"- 제목: {i['title']}\n  블로그: {i['source']}\n  링크: {i['link']}\n  요약: {i.get('description','')}"
        for i in items
    ])
    return header + "\n[블로그 데이터]\n" + context


# ─────────────────────────────
# 🚀 실행 (비동기 스트리밍)
# ─────────────────────────────
async def run(plan) -> AsyncGenerator[ToolChunk, None]:
    query = plan.args.get("query", "")
    yield ToolChunk(type="status", payload=f"📝 '{query}' 관련 블로그 탐색 중...")

    async with aiohttp.ClientSession() as session:
        google_task = asyncio.create_task(get_google_blogs(session, query))
        naver_task = asyncio.create_task(get_naver_blogs(session, query))
        google, naver = await asyncio.gather(google_task, naver_task)

    items = unique_preserve_order(naver + google)
    if not items:
        yield ToolChunk(type="error", payload="❌ 관련 블로그 글을 찾지 못했습니다.")
        return

    yield ToolChunk(type="status", payload=f"🧠 GPT가 {len(items)}건 요약 중...")

    prompt = build_prompt(query, items)
    stream = await settings.openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        stream=True,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield ToolChunk(type="text", payload=delta)

    yield ToolChunk(
        type="source",
        payload=[{"title": i["title"], "link": i["link"], "source": i["source"]} for i in items[:5]],
    )
    yield ToolChunk(type="status", payload="✅ 블로그 요약 완료")
