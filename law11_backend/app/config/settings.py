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

qdrant_client = AsyncQdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60.0)

# ─────────────────────────────
# 🔎 외부 검색 API 설정
# ─────────────────────────────
GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_SEARCH_API_KEY")
GOOGLE_SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# ─────────────────────────────
# ⚖️ 법제처 DRF API
# ─────────────────────────────
LAW_OC_ID = os.getenv("LAW_OC_ID", "drsgh1")

# ─────────────────────────────
# ⚙️ 기타 설정
# ─────────────────────────────
ENABLE_LAW_FALLBACK = os.getenv("ENABLE_LAW_FALLBACK", "true").lower() == "true"
