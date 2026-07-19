#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Law11 — Production-Grade Async DRF Law Updater
================================================================
완전 비동기 법령 최신화 시스템 (10명 동시 서비스 대응)

주요 기능:
- ✅ 완전 비동기 아키텍처 (asyncio + aiohttp + asyncpg)
- ✅ 동시성 제어 (Semaphore로 API 호출 제한)
- ✅ 자동 재시도 로직 (exponential backoff)
- ✅ 진행 상황 표시 (rich progress bar)
- ✅ 에러 핸들링 및 로깅
- ✅ 트랜잭션 관리
- ✅ 배치 처리 최적화

사용법:
    python law_updater_async.py --all
    python law_updater_async.py --law "산업안전보건기준에관한규칙"

스케줄링 (크론):
    0 3 * * * cd /app && python app/tools/law_updater_async.py --all >> /var/log/law_updater.log 2>&1
"""

import os
import re
import sys
import json
import argparse
import uuid
import hashlib
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager

import aiohttp
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from openai import AsyncOpenAI

# Rich for beautiful progress bars
try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("⚠️  pip install rich 권장 (진행 상황 표시)")

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
COLLECTION = "laws"

BASE_URL = "https://www.law.go.kr/DRF/lawService.do"
LAW_ID_MAP: Dict[str, str] = {
    "산업안전보건법": "001766",
    "산업안전보건법시행령": "003786",
    "산업안전보건법시행규칙": "007364",
    "산업안전보건기준에관한규칙": "007363",
    "재난및안전관리기본법": "009640",
    "재난및안전관리기본법시행령": "009708",
    "재난및안전관리기본법시행규칙": "009717",
    "중대재해처벌등에관한법률": "013993",
    "중대재해처벌등에관한법률시행령": "014159",
}

# Concurrency settings
MAX_CONCURRENT_REQUESTS = 3  # 동시 HTTP 요청 수
MAX_CONCURRENT_EMBEDDINGS = 5  # 동시 임베딩 생성 수
BATCH_SIZE = 100  # Qdrant 배치 크기
MAX_RETRIES = 3  # 최대 재시도 횟수

console = Console() if RICH_AVAILABLE else None

# ────────────────────────────────────────────────────────────────
# 유틸리티 함수
# ────────────────────────────────────────────────────────────────

def normalize_law_name(name: str) -> str:
    """법령명 정규화"""
    import unicodedata
    name = unicodedata.normalize("NFC", name or "")
    name = re.sub(r"[\s·]", "", name)
    return name.strip()


def normalize_article(article: str) -> str:
    """조문번호 정규화 (숫자만)"""
    return re.sub(r"[^\d]", "", article or "")


def qdrant_point_id(law_name_norm: str, article_number_norm: str) -> int:
    """(법령, 조문) 기반 결정론적 Qdrant point id.

    upsert와 폐지 조문 삭제가 반드시 같은 계산을 써야 하므로 한 곳에 둔다.
    ⚠️ Python hash()는 프로세스마다 솔트가 달라 불안정했음 (v1.6.0에서 md5로 교체).
    """
    return int(hashlib.md5(
        f"{law_name_norm}:{article_number_norm}".encode()
    ).hexdigest()[:12], 16)


def clean_text(text: str) -> str:
    """
    유니코드 문제 문자 제거 및 정제
    - Surrogate pair 제거
    - 유니코드 정규화 (NFKC)
    - 제어 문자 제거 (줄바꿈/탭 제외)
    """
    if not text:
        return ""
    
    import unicodedata
    
    # 1. Surrogate pair 및 인코딩 불가능한 문자 제거
    text = text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
    
    # 2. 유니코드 정규화 (호환성 분해 후 재결합)
    text = unicodedata.normalize('NFKC', text)
    
    # 3. 제어 문자 제거 (줄바꿈, 탭은 유지)
    text = ''.join(
        char for char in text 
        if char in ('\n', '\t') or not unicodedata.category(char).startswith('C')
    )
    
    return text.strip()


# "항번호"/"호번호"/"목번호"/"조문번호"는 이미 해당 "*내용" 필드 텍스트 안에
# 번호가 포함되어 있으므로(예: "1 제4조...") 별도 추출 시 번호가 중복된다.
# 항/호/목 같은 컨테이너 키는 재귀 대상이어야 하므로 화이트리스트가 아닌
# 정확한 메타 키 이름 목록으로 걸러낸다 (패턴 매칭보다 오탐/누락이 적음).
_NUMBER_ONLY_KEYS = {"항번호", "호번호", "목번호", "조문번호"}


def deep_extract_text(value) -> List[str]:
    """DRF JSON에서 모든 텍스트 추출"""
    out = []
    if isinstance(value, list):
        for v in value:
            out.extend(deep_extract_text(v))
    elif isinstance(value, dict):
        for k, v in value.items():
            if k in _NUMBER_ONLY_KEYS or k.startswith("@"):
                continue
            out.extend(deep_extract_text(v))
    elif isinstance(value, str):
        t = value.strip()
        if t:
            out.append(t)
    return out


def extract_article_payloads(law_name: str, drf_json: dict) -> List[dict]:
    """DRF JSON → 조문 리스트 변환"""
    articles = drf_json.get("법령", {}).get("조문", {})
    if isinstance(articles, dict):
        articles = articles.get("조문단위", [articles])

    payloads = []
    for a in articles or []:
        if a.get("조문여부") != "조문":
            continue  # 편/장 제목 제외

        art_no = normalize_article(str(a.get("조문번호", "")))
        if not art_no:
            continue

        # ⚠️ 가지조문(제N조의M): DRF는 조문번호("14")와 조문가지번호("2")를 분리해
        # 준다. 예전엔 가지번호를 무시해 제14조와 제14조의2가 같은 norm "14"로
        # 뭉개졌고, upsert가 뒤에 온 조문으로 본문을 덮어써 본조가 통째로 소실됐다
        # (실측: 재난법 제14조 중앙재난안전대책본부가 DB에 없었음 — v1.6.0 수정).
        # norm 스킴은 "N" 또는 "N의M" — law_rag_tool.normalize_article과 한 쌍.
        branch = normalize_article(str(a.get("조문가지번호") or ""))
        display_no = f"제{art_no}조의{branch}" if branch else f"제{art_no}조"
        if branch:
            art_no = f"{art_no}의{branch}"

        # 텍스트 추출
        text_candidates = []
        if a.get("조문내용"):
            text_candidates.extend(deep_extract_text(a.get("조문내용")))
        if a.get("항"):
            text_candidates.extend(deep_extract_text(a.get("항")))
        if a.get("조문단위"):
            text_candidates.extend(deep_extract_text(a.get("조문단위")))

        full_text = "\n".join([t for t in text_candidates if t]).strip()
        if not full_text:
            title = a.get("조문제목") or ""
            body = a.get("조문내용") or ""
            body_str = " ".join(deep_extract_text(body)) if body else ""
            full_text = (f"{title} {body_str}").strip()

        # 시행일자
        enf = a.get("조문시행일자") or drf_json.get("법령", {}).get("시행일자") or drf_json.get("법령", {}).get("시행일")
        if isinstance(enf, list):
            enf = enf[-1]
        if isinstance(enf, dict):
            enf = enf.get("@시행일자") or enf.get("#text")
        enforcement_date = (str(enf).strip() if enf else None) or ""

        if enforcement_date:
            enforcement_date = enforcement_date[:10]
            # DATE 타입으로 변환: "20251001" → datetime.date 객체
            try:
                if len(enforcement_date) == 8 and enforcement_date.isdigit():
                    # YYYYMMDD → date 객체
                    enforcement_date = datetime.strptime(enforcement_date, "%Y%m%d").date()
                elif len(enforcement_date) == 10 and enforcement_date[4] == '-':
                    # YYYY-MM-DD → date 객체
                    enforcement_date = datetime.strptime(enforcement_date, "%Y-%m-%d").date()
                else:
                    enforcement_date = None
            except (ValueError, AttributeError):
                enforcement_date = None  # 잘못된 형식은 NULL

        # 삭제된 조문("제9조의2 삭제 <2013.8.6>")은 본문이 없어 RAG에 무의미 — 제외
        if re.match(r"^제\s*\d+\s*조(?:의\s*\d+)?\s*삭제", full_text.strip()):
            continue

        if full_text:
            payloads.append({
                "chunk_id": str(uuid.uuid4()),
                "law_name": law_name,
                "law_name_norm": normalize_law_name(law_name),
                "article_number": display_no,
                "article_number_norm": art_no,
                "text": clean_text(full_text),
                "enforcement_date": enforcement_date,
            })
    return payloads


# ────────────────────────────────────────────────────────────────
# 비동기 클라이언트 관리
# ────────────────────────────────────────────────────────────────

class AsyncLawUpdater:
    """완전 비동기 법령 업데이터"""

    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.engine: Optional[AsyncEngine] = None
        self.qdrant: Optional[QdrantClient] = None
        self.session: Optional[aiohttp.ClientSession] = None

        # Semaphores for concurrency control
        self.http_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        self.embed_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EMBEDDINGS)

    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.cleanup()

    async def initialize(self):
        """클라이언트 초기화"""
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY missing in environment")

        # AsyncEngine (asyncpg 사용)
        db_url = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        self.engine = create_async_engine(
            db_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False
        )

        # Qdrant (동기 클라이언트 - 내부적으로 비동기 사용)
        self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=120)

        # aiohttp session
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)

        # 스키마 초기화
        await self.ensure_pg_schema()
        await asyncio.to_thread(self.ensure_qdrant_schema)

    async def cleanup(self):
        """리소스 정리"""
        if self.session:
            await self.session.close()
        if self.engine:
            await self.engine.dispose()

    async def ensure_pg_schema(self):
        """PostgreSQL 테이블 생성"""
        # AsyncPG는 prepared statement에서 여러 명령을 동시 실행 불가 → 분리 실행
        async with self.engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS law_chunks (
                    id SERIAL PRIMARY KEY,
                    chunk_id TEXT UNIQUE,
                    law_name TEXT NOT NULL,
                    law_name_norm TEXT NOT NULL,
                    article_number TEXT,
                    article_number_norm TEXT NOT NULL,
                    text TEXT NOT NULL,
                    enforcement_date DATE,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.execute(text(
                "ALTER TABLE law_chunks ADD COLUMN IF NOT EXISTS article_number TEXT"
            ))
            await conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_law_chunks_unique
                    ON law_chunks (law_name_norm, article_number_norm)
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_law_chunks_law_name
                    ON law_chunks (law_name_norm)
            """))

    def ensure_qdrant_schema(self):
        """Qdrant 컬렉션 생성 (동기)"""
        try:
            self.qdrant.get_collection(COLLECTION)
        except Exception:
            self.qdrant.recreate_collection(
                collection_name=COLLECTION,
                vectors_config=qmodels.VectorParams(
                    size=EMBED_DIM,
                    distance=qmodels.Distance.COSINE
                ),
            )

    # ────────────────────────────────────────────────────────────
    # HTTP 요청 (aiohttp + 재시도)
    # ────────────────────────────────────────────────────────────

    async def fetch_drf_json_with_retry(self, law_name: str) -> dict:
        """법제처 DRF API 호출 (재시도 로직)"""
        law_id = LAW_ID_MAP.get(law_name, law_name)
        params = {
            "OC": LAW_OC_ID,
            "target": "law",
            "ID": law_id,
            "type": "JSON"
        }

        for attempt in range(MAX_RETRIES):
            try:
                async with self.http_semaphore:
                    async with self.session.get(BASE_URL, params=params) as resp:
                        resp.raise_for_status()
                        return await resp.json()
            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait_time = 2 ** attempt  # Exponential backoff
                if console:
                    console.print(f"⚠️  [{law_name}] 재시도 {attempt + 1}/{MAX_RETRIES} (대기: {wait_time}초)")
                await asyncio.sleep(wait_time)

    # ────────────────────────────────────────────────────────────
    # PostgreSQL 업서트 (비동기)
    # ────────────────────────────────────────────────────────────

    async def upsert_pg(self, rows: List[dict]):
        """PostgreSQL 배치 upsert"""
        if not rows:
            return

        sql = text("""
            INSERT INTO law_chunks (
                chunk_id, law_name, law_name_norm, article_number, article_number_norm, text, enforcement_date
            )
            VALUES (
                :chunk_id, :law_name, :law_name_norm, :article_number, :article_number_norm, :text, :enforcement_date
            )
            ON CONFLICT (law_name_norm, article_number_norm)
            DO UPDATE SET
                article_number = EXCLUDED.article_number,
                text = EXCLUDED.text,
                enforcement_date = EXCLUDED.enforcement_date,
                updated_at = CURRENT_TIMESTAMP;
        """)

        async with self.engine.begin() as conn:
            await conn.execute(sql, rows)

    # ────────────────────────────────────────────────────────────
    # Qdrant 업서트 (비동기 임베딩)
    # ────────────────────────────────────────────────────────────

    async def create_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """배치 임베딩 생성 (동시성 제어)"""
        # 텍스트 정제 (유니코드 문제 문자 제거)
        cleaned_texts = [clean_text(text) for text in texts]
        
        async with self.embed_semaphore:
            response = await self.openai_client.embeddings.create(
                model=EMBED_MODEL,
                input=cleaned_texts
            )
            return [item.embedding for item in response.data]

    async def upsert_qdrant(self, rows: List[dict], progress_callback=None):
        """Qdrant 배치 업로드 (비동기 임베딩)"""
        if not rows:
            return

        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]

            # 임베딩 생성 (비동기)
            texts = [r["text"] for r in batch]
            vectors = await self.create_embeddings_batch(texts)

            # Qdrant 포인트 생성
            points = []
            for r, vec in zip(batch, vectors):
                pid = qdrant_point_id(r["law_name_norm"], r["article_number_norm"])
                payload = {
                    "law_name": r["law_name"],
                    "law_name_norm": r["law_name_norm"],
                    "article_number": r["article_number"],
                    "article_number_norm": r["article_number_norm"],
                    "text": r["text"],
                    "enforcement_date": r["enforcement_date"],
                }
                points.append(qmodels.PointStruct(id=pid, vector=vec, payload=payload))

            # Qdrant 업로드 (동기 함수를 비동기로 실행)
            await asyncio.to_thread(
                self.qdrant.upsert,
                collection_name=COLLECTION,
                points=points
            )

            if progress_callback:
                progress_callback(len(batch))

            # 과부하 방지
            await asyncio.sleep(0.2)

    # ────────────────────────────────────────────────────────────
    # 법령 업데이트 로직
    # ────────────────────────────────────────────────────────────

    async def remove_stale_articles(self, law_name_norm: str, current_norms: set) -> tuple:
        """API 최신본에서 사라진(폐지·이관) 조문을 PG·Qdrant 양쪽에서 제거.

        upsert만으로는 폐지 조문이 영원히 검색된다 — 법률 챗봇에서 폐지된
        조문을 현행처럼 인용하는 오답 리스크 (README #32). 호출 전제:
        current_norms는 방금 성공한 fetch에서 나온 비어있지 않은 집합이어야
        한다. fetch 실패/빈 응답 시에는 호출되지 않으므로(update_one_law가
        먼저 return) API 장애가 대량 오삭제로 번지지 않는다.
        """
        norms = list(current_norms)

        async with self.engine.begin() as conn:
            res = await conn.execute(
                text("""
                    DELETE FROM law_chunks
                    WHERE law_name_norm = :law
                      AND NOT (article_number_norm = ANY(:norms))
                """),
                {"law": law_name_norm, "norms": norms},
            )
        pg_removed = res.rowcount or 0

        # Qdrant: 해당 법령의 기존 point id를 전부 걷어 기대 집합에 없는 것 삭제
        expected_ids = {qdrant_point_id(law_name_norm, n) for n in current_norms}
        law_filter = qmodels.Filter(must=[
            qmodels.FieldCondition(key="law_name_norm", match=qmodels.MatchValue(value=law_name_norm))
        ])
        stale_ids = []
        offset = None
        while True:
            points, offset = await asyncio.to_thread(
                self.qdrant.scroll,
                collection_name=COLLECTION,
                scroll_filter=law_filter,
                limit=500,
                with_payload=False,
                with_vectors=False,
                offset=offset,
            )
            stale_ids.extend(p.id for p in points if p.id not in expected_ids)
            if offset is None:
                break
        if stale_ids:
            await asyncio.to_thread(
                self.qdrant.delete,
                collection_name=COLLECTION,
                points_selector=qmodels.PointIdsList(points=stale_ids),
            )
        return pg_removed, len(stale_ids)

    async def verify_consistency(self) -> bool:
        """동기화 후 PG↔Qdrant 법령별 조문 수 대조.

        동기화가 중간에 죽으면 한쪽만 갱신된 불일치가 조용히 남는다 — 주간
        스케줄러가 이를 알아차릴 수 있도록 매 동기화 끝에 실행 (README #32).
        """
        _print = console.print if console else print

        async with self.engine.connect() as conn:
            res = await conn.execute(text(
                "SELECT law_name_norm, count(*) FROM law_chunks GROUP BY law_name_norm"
            ))
            pg_counts = {r[0]: r[1] for r in res.fetchall()}

        ok = True
        _print("\n🔎 PG ↔ Qdrant 정합성 검증")
        for law_norm in sorted(pg_counts):
            pg_n = pg_counts[law_norm]
            qd = await asyncio.to_thread(
                self.qdrant.count,
                collection_name=COLLECTION,
                count_filter=qmodels.Filter(must=[
                    qmodels.FieldCondition(key="law_name_norm", match=qmodels.MatchValue(value=law_norm))
                ]),
                exact=True,
            )
            if qd.count != pg_n:
                ok = False
                _print(f"  ❌ {law_norm}: PG {pg_n} ≠ Qdrant {qd.count}")

        # 총합 대조 — PG에 없는 법령이 Qdrant에만 남은 경우까지 잡는다
        total_pg = sum(pg_counts.values())
        total_qd = await asyncio.to_thread(self.qdrant.count, collection_name=COLLECTION, exact=True)
        if total_qd.count != total_pg:
            ok = False
            _print(f"  ❌ 총합 불일치: PG {total_pg} ≠ Qdrant {total_qd.count}")

        if ok:
            _print(f"  ✅ 일치: {len(pg_counts)}개 법령, 총 {total_pg}개 조문")
        else:
            _print("  ⚠️ 불일치 감지 — 전체 재동기화(--all) 또는 수동 확인 필요")
        return ok

    async def update_one_law(self, law_name: str) -> int:
        """단일 법령 업데이트"""
        try:
            if console:
                console.print(f"\n🔄 [{law_name}] DRF API 호출 중...")

            # 1. DRF JSON 가져오기
            drf_json = await self.fetch_drf_json_with_retry(law_name)

            # 2. 조문 추출
            rows = extract_article_payloads(law_name, drf_json)
            if not rows:
                if console:
                    console.print(f"⚠️  [{law_name}] 추출된 조문 없음", style="yellow")
                return 0

            if console:
                console.print(f"📝 [{law_name}] {len(rows)}개 조문 추출 완료")

            # 3. PostgreSQL 업데이트
            await self.upsert_pg(rows)
            if console:
                console.print(f"✅ [{law_name}] PostgreSQL 저장 완료")

            # 4. Qdrant 업데이트 (임베딩 생성)
            if console:
                console.print(f"🧠 [{law_name}] 임베딩 생성 및 Qdrant 업로드 중...")

            uploaded = 0
            def update_progress(count):
                nonlocal uploaded
                uploaded += count

            await self.upsert_qdrant(rows, progress_callback=update_progress)

            # 5. 폐지 조문 제거 (최신본 fetch 성공 시에만 도달)
            current_norms = {r["article_number_norm"] for r in rows}
            pg_rm, qd_rm = await self.remove_stale_articles(rows[0]["law_name_norm"], current_norms)
            if (pg_rm or qd_rm) and console:
                console.print(f"🗑️  [{law_name}] 폐지 조문 제거: PG {pg_rm}개 / Qdrant {qd_rm}개")

            if console:
                console.print(f"✅ [{law_name}] 완료: {len(rows)}개 조문 동기화", style="green bold")

            return len(rows)

        except Exception as e:
            if console:
                console.print(f"❌ [{law_name}] 실패: {e}", style="red bold")
            else:
                print(f"❌ [{law_name}] 실패: {e}")
            return 0

    async def update_all(self):
        """모든 법령 업데이트 (동시 처리)"""
        if console:
            console.print("\n🚀 법령 최신화 시작", style="cyan bold")
            console.print(f"📚 대상: {len(LAW_ID_MAP)}개 법령\n")

        start_time = asyncio.get_event_loop().time()

        # 모든 법령을 동시에 처리 (Semaphore로 제어)
        tasks = [self.update_one_law(law_name) for law_name in LAW_ID_MAP.keys()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과 집계
        total_articles = sum(r for r in results if isinstance(r, int))
        failed = sum(1 for r in results if isinstance(r, Exception))

        elapsed = asyncio.get_event_loop().time() - start_time

        if console:
            console.print(f"\n🎉 완료!", style="green bold")
            console.print(f"📊 총 {total_articles}개 조문 동기화")
            console.print(f"⏱️  소요 시간: {elapsed:.1f}초")
            if failed > 0:
                console.print(f"⚠️  실패: {failed}개 법령", style="yellow")
        else:
            print(f"\n🎉 완료: {total_articles}개 조문 동기화 ({elapsed:.1f}초)")

        return await self.verify_consistency()


# ────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────

async def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description="Law11 비동기 법령 최신화 도구 (Production-Grade)"
    )
    parser.add_argument("--all", action="store_true", help="모든 법령 최신화")
    parser.add_argument("--law", type=str, help="특정 법령명만 최신화")
    args = parser.parse_args()

    if not args.all and not args.law:
        parser.print_help()
        sys.exit(1)

    async with AsyncLawUpdater() as updater:
        if args.all:
            consistent = await updater.update_all()
            if not consistent:
                sys.exit(1)   # CI/cron에서 불일치를 실패로 감지
        elif args.law:
            count = await updater.update_one_law(args.law)
            if console:
                console.print(f"\n✅ {args.law}: {count}개 조문 동기화 완료")
            if not await updater.verify_consistency():
                sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())