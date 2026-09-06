# law11_backend/app/config/settings.py
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import create_async_engine
from qdrant_client import AsyncQdrantClient
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────
# 📁 .env 로드 (환경별 자동 감지)
# ─────────────────────────────
# Docker: /app/.env
# Local: {project_root}/law11_backend/.env
ENV_PATH = Path(__file__).parent.parent.parent / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
    logger.info(f"✅ Loaded .env from: {ENV_PATH}")
else:
    # docker-compose의 env_file 또는 시스템 환경변수 사용
    load_dotenv()
    logger.warning("⚠️ .env file not found, using system environment variables")

# ─────────────────────────────
# 🤖 OpenAI 설정
# ─────────────────────────────
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
OPENAI_PROJECT_ID: Optional[str] = os.getenv("OPENAI_PROJECT_ID")

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY is required but not set in environment variables")

# ✅ 비동기 클라이언트 (한 번만 생성해서 재사용)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, project=OPENAI_PROJECT_ID)

# ⚠️ openai SDK 기본 timeout(10분)은 실제 사용자 질문 처리엔 너무 길다 — 하나의
# 요청이 오래 매달리면 uvicorn --workers 2(동시 10명 설계 목표) 안에서 다른
# 사용자 요청까지 지연될 수 있다. 명시적으로 짧게 잡아 빠르게 실패시킨다.
GPT_TIMEOUT_SECONDS = 60

# ─────────────────────────────
# 🗄️ PostgreSQL 설정 (비동기 엔진)
# ─────────────────────────────
# Docker: postgres (서비스명), Local: localhost
DB_NAME = os.getenv("DB_NAME", "law11")
DB_USER = os.getenv("DB_USER", "daniel")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST", "postgres")  # Docker 서비스명
DB_PORT = int(os.getenv("DB_PORT", 5432))

if not DB_PASS:
    raise ValueError("❌ DB_PASS is required but not set in environment variables")

ASYNC_DB_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ✅ Connection Pool 튜닝
async_engine = create_async_engine(
    ASYNC_DB_URL,
    echo=False,
    future=True,
    pool_size=10,          # 기본 5 → 10명 동시 연결 허용
    max_overflow=20,       # 추가 임시 연결 20개까지 허용
    pool_timeout=30,       # 연결 대기시간 (초)
    pool_pre_ping=True,    # 연결 유효성 사전 체크
)

# ─────────────────────────────
# 🧠 Qdrant 설정 (비동기 클라이언트)
# ─────────────────────────────
# Docker: qdrant (서비스명), Local: localhost
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "laws")
QDRANT_CASE_LAW_COLLECTION_NAME = os.getenv("QDRANT_CASE_LAW_COLLECTION_NAME", "case_laws")

qdrant_client = AsyncQdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60.0)

# ─────────────────────────────
# 🔎 외부 검색 API 설정
# ─────────────────────────────
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# ─────────────────────────────
# 🤖 모델 지정 (단일 소스)
# ─────────────────────────────
# 예전엔 model="gpt-4o-mini"가 14개 파일에 문자열로 흩어져 있어, 모델을 바꾸려면
# 전부 찾아 고쳐야 했고 일부만 바꿔 불일치가 나기 쉬웠다. 컬렉션명(QDRANT_*)과
# 같은 규칙으로 여기 한 곳에서만 관리한다.
# ⚠️ 생성·라우팅·판정이 모두 같은 모델을 쓰는 게 현재 설계다(모델 티어링 미적용).
#    난이도별로 나눌 일이 생기면 여기에 상수를 추가하고 호출부에서 골라 쓰면 된다.
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")

# ─────────────────────────────
# 🔐 관리자 엔드포인트 인증
# ─────────────────────────────
# /api/admin/* 는 법령 전체 재수집(임베딩 수천 건 = 비용 발생)과 chat_history
# 덤프를 트리거하므로 인증이 필요하다. 미설정 시 해당 엔드포인트는 503으로
# 비활성화된다(fail-closed) — 키가 없다고 무인증으로 열어두면 안 되기 때문.
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# ─────────────────────────────
# 🌐 CORS 설정
# ─────────────────────────────
# .env의 CORS_ORIGINS(콤마 구분)로 배포 도메인 추가. 미설정 시 로컬 개발 기본값 사용.
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5173,http://localhost:5174,http://localhost:5177,"
    "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5177"
)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
