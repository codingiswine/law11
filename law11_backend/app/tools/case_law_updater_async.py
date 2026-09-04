#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Law11 — Async DRF Case Law (판례) Updater
================================================================
9개 추적 법령을 인용하는 대법원 판례를 법제처 DRF Open API(target=prec)로
수집한다. law_updater_async.py의 구조를 그대로 미러링하되, 판례 고유의
차이점을 반영한다:

- 자연키가 법조문처럼 (법령, 조문번호) 복합키가 아니라 `판례정보일련번호`
  (소스가 부여하는 정수) 하나뿐이라 md5 point-id 해싱이 불필요하다.
- 판례는 선고된 뒤 불변이다. 법조문처럼 개정/폐지로 사라지는 일이 없으므로
  remove_stale_articles에 해당하는 삭제 로직을 두지 않는다 — 페이지네이션
  결과에서 특정 판례가 빠졌다고 삭제하면 실제로 존재하는 판례를 지우는
  오류가 된다.
- 수집 범위는 9개 추적 법령(LAW_ID_MAP)을 인용하는 대법원 판례로 한정
  (JO=<법령명>&org=400201), 법령당 상한 MAX_CASES_PER_LAW건. 무제한
  자유검색은 하지 않는다.

사용법:
    python case_law_updater_async.py --all
    python case_law_updater_async.py --law "산업안전보건법"

스케줄링: app/services/law_scheduler.py의 weekly_case_law_update job
"""

import os
import re
import sys
import argparse
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime

import aiohttp
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from openai import AsyncOpenAI

try:
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from app.tools.law_updater_async import LAW_ID_MAP, normalize_law_name, clean_text

# ────────────────────────────────────────────────────────────────
# 환경설정
# ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(os.path.abspath(os.path.join(BASE_DIR, "..", "..")), ".env")
load_dotenv(ENV_PATH) if os.path.exists(ENV_PATH) else load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_USER = os.getenv("DB_USER", "daniel")
DB_PASS = os.getenv("DB_PASS", "")
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "law11")
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
LAW_OC_ID = os.getenv("LAW_OC_ID", "drsgh1")

EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072
COLLECTION = os.getenv("QDRANT_CASE_LAW_COLLECTION_NAME", "case_laws")

SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL_URL = "https://www.law.go.kr/DRF/lawService.do"
SUPREME_COURT_CODE = "400201"  # org= 파라미터 값이자 응답의 법원종류코드 값 (실측 확인됨)

MAX_CASES_PER_LAW = 100  # 법령당 상한 (제품 결정, 사용자 확인됨)
MAX_CONCURRENT_REQUESTS = 3
MAX_CONCURRENT_EMBEDDINGS = 5
BATCH_SIZE = 100
MAX_RETRIES = 3

console = Console() if RICH_AVAILABLE else None

# ────────────────────────────────────────────────────────────────
# 유틸리티 함수
# ────────────────────────────────────────────────────────────────

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(value: Optional[str]) -> str:
    """DRF 판례 필드에 섞여 나오는 <br/> 등 HTML 태그 제거 (실측 확인됨)."""
    if not value:
        return ""
    return _HTML_TAG_RE.sub("", value).strip()


def normalize_case_number(case_number: str) -> str:
    """사건번호 정규화 — 공백/전각 문자만 제거. 조문처럼 가지번호 스킴 없음."""
    import unicodedata
    s = unicodedata.normalize("NFC", case_number or "")
    return re.sub(r"\s", "", s)


def parse_judgment_date(raw: Optional[str]):
    """선고일자 파싱. 상세조회는 'YYYYMMDD', 검색결과는 'YYYY.MM.DD' 형태(실측 확인됨)."""
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) != 8:
        return None
    try:
        return datetime.strptime(digits, "%Y%m%d").date()
    except ValueError:
        return None


# ────────────────────────────────────────────────────────────────
# 비동기 클라이언트 관리
# ────────────────────────────────────────────────────────────────

class AsyncCaseLawUpdater:
    """완전 비동기 판례 업데이터"""

    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.engine: Optional[AsyncEngine] = None
        self.qdrant: Optional[QdrantClient] = None
        self.session: Optional[aiohttp.ClientSession] = None

        self.http_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self.embed_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EMBEDDINGS)

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    async def initialize(self):
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY missing in environment")

        db_url = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        self.engine = create_async_engine(
            db_url, pool_size=10, max_overflow=20, pool_pre_ping=True, echo=False
        )
        self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=120)
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)

        await self.ensure_pg_schema()
        await asyncio.to_thread(self.ensure_qdrant_schema)

    async def cleanup(self):
        if self.session:
            await self.session.close()
        if self.engine:
            await self.engine.dispose()

    async def ensure_pg_schema(self):
        """PostgreSQL 테이블 생성 (init.sql과 동일 스키마 — 로컬 실행 시 init.sql이
        아직 안 돌았을 수 있으므로 law_updater_async.py 관례를 따라 여기서도 보장)."""
        async with self.engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS case_law_chunks (
                    id SERIAL PRIMARY KEY,
                    prec_serial_no INTEGER UNIQUE NOT NULL,
                    case_name VARCHAR(500),
                    case_number VARCHAR(100),
                    case_number_norm VARCHAR(100),
                    court_name VARCHAR(255),
                    court_type_code VARCHAR(20),
                    judgment_date DATE,
                    case_type_name VARCHAR(100),
                    judgment_type VARCHAR(100),
                    holding_summary TEXT,
                    ruling_gist TEXT,
                    full_text TEXT,
                    referenced_statutes TEXT,
                    referenced_cases TEXT,
                    source_law_norm VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_case_law_chunks_prec_id
                    ON case_law_chunks (prec_serial_no)
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_case_law_chunks_source_law_norm
                    ON case_law_chunks (source_law_norm)
            """))

    def ensure_qdrant_schema(self):
        try:
            self.qdrant.get_collection(COLLECTION)
        except Exception:
            self.qdrant.recreate_collection(
                collection_name=COLLECTION,
                vectors_config=qmodels.VectorParams(size=EMBED_DIM, distance=qmodels.Distance.COSINE),
            )

    # ────────────────────────────────────────────────────────────
    # HTTP 요청 (검색 + 상세, 재시도)
    # ────────────────────────────────────────────────────────────

    async def _get_json_with_retry(self, url: str, params: dict, label: str) -> dict:
        for attempt in range(MAX_RETRIES):
            try:
                async with self.http_semaphore:
                    async with self.session.get(url, params=params) as resp:
                        resp.raise_for_status()
                        return await resp.json()
            except Exception:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait_time = 2 ** attempt
                if console:
                    console.print(f"⚠️  [{label}] 재시도 {attempt + 1}/{MAX_RETRIES} (대기: {wait_time}초)")
                await asyncio.sleep(wait_time)

    async def search_cases_for_law(self, law_name: str) -> List[dict]:
        """JO=<법령명>&org=대법원으로 판례 검색, 법령당 상한까지 페이지네이션."""
        results: List[dict] = []
        page = 1
        display = 100
        while len(results) < MAX_CASES_PER_LAW:
            params = {
                "OC": LAW_OC_ID, "target": "prec", "type": "JSON",
                "JO": law_name, "org": SUPREME_COURT_CODE,
                "display": display, "page": page,
            }
            data = await self._get_json_with_retry(SEARCH_URL, params, f"{law_name} 검색")
            items = (data.get("PrecSearch") or {}).get("prec") or []
            if not items:
                break
            results.extend(items)
            if len(items) < display:
                break
            page += 1
        return results[:MAX_CASES_PER_LAW]

    async def fetch_case_detail(self, prec_serial_no: str) -> dict:
        params = {"OC": LAW_OC_ID, "target": "prec", "type": "JSON", "ID": prec_serial_no}
        data = await self._get_json_with_retry(DETAIL_URL, params, f"판례 {prec_serial_no} 상세")
        return (data.get("PrecService") or {})

    # ────────────────────────────────────────────────────────────
    # PostgreSQL 업서트
    # ────────────────────────────────────────────────────────────

    async def upsert_pg(self, rows: List[dict]):
        if not rows:
            return
        sql = text("""
            INSERT INTO case_law_chunks (
                prec_serial_no, case_name, case_number, case_number_norm,
                court_name, court_type_code, judgment_date, case_type_name,
                judgment_type, holding_summary, ruling_gist, full_text,
                referenced_statutes, referenced_cases, source_law_norm
            )
            VALUES (
                :prec_serial_no, :case_name, :case_number, :case_number_norm,
                :court_name, :court_type_code, :judgment_date, :case_type_name,
                :judgment_type, :holding_summary, :ruling_gist, :full_text,
                :referenced_statutes, :referenced_cases, :source_law_norm
            )
            ON CONFLICT (prec_serial_no)
            DO UPDATE SET
                case_name = EXCLUDED.case_name,
                holding_summary = EXCLUDED.holding_summary,
                ruling_gist = EXCLUDED.ruling_gist,
                full_text = EXCLUDED.full_text,
                referenced_statutes = EXCLUDED.referenced_statutes,
                referenced_cases = EXCLUDED.referenced_cases,
                updated_at = CURRENT_TIMESTAMP;
        """)
        async with self.engine.begin() as conn:
            await conn.execute(sql, rows)

    # ────────────────────────────────────────────────────────────
    # Qdrant 업서트 (비동기 임베딩)
    # ────────────────────────────────────────────────────────────

    async def create_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        cleaned = [clean_text(t) for t in texts]
        async with self.embed_semaphore:
            response = await self.openai_client.embeddings.create(model=EMBED_MODEL, input=cleaned)
            return [item.embedding for item in response.data]

    async def upsert_qdrant(self, rows: List[dict]):
        if not rows:
            return
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            # 임베딩 소스: 판시사항+판결요지만 (전문은 8191토큰 한도 초과 위험 — 실측 확인, 표시 전용)
            texts = [f"{r['holding_summary']}\n{r['ruling_gist']}".strip() for r in batch]
            vectors = await self.create_embeddings_batch(texts)

            points = []
            for r, vec in zip(batch, vectors):
                payload = {
                    "prec_serial_no": r["prec_serial_no"],
                    "case_name": r["case_name"],
                    "case_number": r["case_number"],
                    "court_name": r["court_name"],
                    "judgment_date": str(r["judgment_date"]) if r["judgment_date"] else None,
                    "holding_summary": r["holding_summary"],
                    "ruling_gist": r["ruling_gist"],
                    "source_law_norm": r["source_law_norm"],
                }
                # point id = prec_serial_no 그대로 (자연키가 이미 유일한 정수라 md5 해싱 불필요)
                points.append(qmodels.PointStruct(id=r["prec_serial_no"], vector=vec, payload=payload))

            await asyncio.to_thread(self.qdrant.upsert, collection_name=COLLECTION, points=points)
            await asyncio.sleep(0.2)

    # ────────────────────────────────────────────────────────────
    # 판례 업데이트 로직
    # ────────────────────────────────────────────────────────────
    # ⚠️ remove_stale_articles에 해당하는 로직 없음 — 판례는 선고 후 불변이므로
    # 페이지네이션에서 빠졌다고 삭제하면 안 됨 (law_updater_async.py와의 의도된 비대칭).

    async def update_cases_for_law(self, law_name: str) -> int:
        try:
            if console:
                console.print(f"\n🔄 [{law_name}] 판례 검색 중...")

            search_results = await self.search_cases_for_law(law_name)
            if not search_results:
                if console:
                    console.print(f"⚠️  [{law_name}] 검색된 판례 없음", style="yellow")
                return 0

            if console:
                console.print(f"📝 [{law_name}] {len(search_results)}건 검색됨, 상세조회 중...")

            law_name_norm = normalize_law_name(law_name)
            rows = []
            for item in search_results:
                prec_id = item.get("판례일련번호")
                if not prec_id:
                    continue
                detail = await self.fetch_case_detail(prec_id)
                if not detail:
                    continue
                # org= 필터가 API 측에서 바뀌더라도 대법원 외 판례가 섞이지 않도록 방어
                if detail.get("법원종류코드") != SUPREME_COURT_CODE:
                    continue
                rows.append({
                    "prec_serial_no": int(detail.get("판례정보일련번호") or prec_id),
                    "case_name": detail.get("사건명", ""),
                    "case_number": detail.get("사건번호", ""),
                    "case_number_norm": normalize_case_number(detail.get("사건번호", "")),
                    "court_name": detail.get("법원명", ""),
                    "court_type_code": detail.get("법원종류코드", ""),
                    "judgment_date": parse_judgment_date(detail.get("선고일자")),
                    "case_type_name": detail.get("사건종류명", ""),
                    "judgment_type": detail.get("판결유형", ""),
                    "holding_summary": strip_html(detail.get("판시사항")),
                    "ruling_gist": strip_html(detail.get("판결요지")),
                    "full_text": strip_html(detail.get("판례내용")),
                    "referenced_statutes": strip_html(detail.get("참조조문")),
                    "referenced_cases": strip_html(detail.get("참조판례")),
                    "source_law_norm": law_name_norm,
                })

            if not rows:
                return 0

            await self.upsert_pg(rows)
            if console:
                console.print(f"✅ [{law_name}] PostgreSQL 저장 완료: {len(rows)}건")

            await self.upsert_qdrant(rows)
            if console:
                console.print(f"✅ [{law_name}] 완료: {len(rows)}건 동기화", style="green bold")

            return len(rows)

        except Exception as e:
            if console:
                console.print(f"❌ [{law_name}] 실패: {e}", style="red bold")
            else:
                print(f"❌ [{law_name}] 실패: {e}")
            return 0

    async def verify_consistency(self) -> bool:
        """동기화 후 PG↔Qdrant source_law_norm별 판례 수 대조."""
        _print = console.print if console else print

        async with self.engine.connect() as conn:
            res = await conn.execute(text(
                "SELECT source_law_norm, count(*) FROM case_law_chunks GROUP BY source_law_norm"
            ))
            pg_counts = {r[0]: r[1] for r in res.fetchall()}

        ok = True
        _print("\n🔎 PG ↔ Qdrant 판례 정합성 검증")
        for law_norm in sorted(pg_counts):
            pg_n = pg_counts[law_norm]
            qd = await asyncio.to_thread(
                self.qdrant.count,
                collection_name=COLLECTION,
                count_filter=qmodels.Filter(must=[
                    qmodels.FieldCondition(key="source_law_norm", match=qmodels.MatchValue(value=law_norm))
                ]),
                exact=True,
            )
            if qd.count != pg_n:
                ok = False
                _print(f"  ❌ {law_norm}: PG {pg_n} ≠ Qdrant {qd.count}")

        if ok:
            _print(f"  ✅ 일치: {len(pg_counts)}개 법령, 총 {sum(pg_counts.values())}건 판례")
        else:
            _print("  ⚠️ 불일치 감지 — 재동기화 또는 수동 확인 필요")
        return ok

    async def update_all(self):
        if console:
            console.print("\n🚀 판례 최신화 시작", style="cyan bold")
            console.print(f"📚 대상: {len(LAW_ID_MAP)}개 법령 (법령당 상한 {MAX_CASES_PER_LAW}건)\n")

        start_time = asyncio.get_event_loop().time()
        total = 0
        for law_name in LAW_ID_MAP.keys():
            total += await self.update_cases_for_law(law_name)
        elapsed = asyncio.get_event_loop().time() - start_time

        if console:
            console.print(f"\n🎉 완료! 총 {total}건 판례 동기화 ({elapsed:.1f}초)", style="green bold")
        else:
            print(f"\n🎉 완료: {total}건 판례 동기화 ({elapsed:.1f}초)")

        return await self.verify_consistency()


# ────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Law11 비동기 판례 최신화 도구")
    parser.add_argument("--all", action="store_true", help="모든 추적 법령의 판례 최신화")
    parser.add_argument("--law", type=str, help="특정 법령명만 최신화")
    args = parser.parse_args()

    if not args.all and not args.law:
        parser.print_help()
        sys.exit(1)

    async with AsyncCaseLawUpdater() as updater:
        if args.all:
            consistent = await updater.update_all()
            if not consistent:
                sys.exit(1)
        elif args.law:
            count = await updater.update_cases_for_law(args.law)
            if console:
                console.print(f"\n✅ {args.law}: {count}건 판례 동기화 완료")
            if not await updater.verify_consistency():
                sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
