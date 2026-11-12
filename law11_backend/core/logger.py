import logging
import os
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

# ─────────────────────────────────────────────
# 📁 1. 로그 폴더
# ─────────────────────────────────────────────
# Docker 환경 고려: /app/logs
BASE_LOG_DIR = Path("/app/logs") if os.path.exists("/app") else Path("logs")
BASE_LOG_DIR.mkdir(parents=True, exist_ok=True)

# ⚠️ 예전엔 임포트 시점의 날짜로 logs/YYYY-MM-DD/ 폴더를 만들어 거기에만 썼다 — 프로세스가
# `restart: unless-stopped`로 몇 주 떠 있으면 모든 로그가 시작일 폴더에 쌓였다 (#90).
# 날짜 분리는 핸들러가 자정에 회전하며 맡는다: server.log → server.log.2026-11-12 …
LOG_DIR = BASE_LOG_DIR

# ─────────────────────────────────────────────
# 📄 2. 로그 파일 경로 설정
# ─────────────────────────────────────────────
CHAT_LOG = LOG_DIR / "chat_history.log"
SERVER_LOG = LOG_DIR / "server.log"
ERROR_LOG = LOG_DIR / "error.log"


def _daily(path: Path, level: int, backup_count: int) -> TimedRotatingFileHandler:
    h = TimedRotatingFileHandler(str(path), when="midnight", backupCount=backup_count, encoding="utf-8")
    h.setLevel(level)
    h.setFormatter(formatter)
    return h

# ─────────────────────────────────────────────
# 🎨 3. 로그 포맷터 (프로덕션 버전)
# ─────────────────────────────────────────────
# 포맷 예시:
# 2025-11-06 15:02:11.123 [INFO] [Law11Logger] {file.py:42} 🚀 [요청 수신] question=소화기 점검 주기
formatter = logging.Formatter(
    "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] {%(filename)s:%(lineno)d} %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 간단한 콘솔용 포맷터
console_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

# ─────────────────────────────────────────────
# 🧠 4. Law11 내부 로거 (GPT / DB / 품질평가 등)
# ─────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

law11_logger = logging.getLogger("Law11Logger")
law11_logger.setLevel(LOG_LEVEL)
law11_logger.propagate = False  # 중복 로깅 방지

# 파일 핸들러 (상세 로그) — 자정 회전, 10일 보관
chat_handler = _daily(CHAT_LOG, logging.DEBUG, backup_count=10)

# 콘솔 핸들러 (간단한 로그)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(console_formatter)

law11_logger.addHandler(chat_handler)
law11_logger.addHandler(console_handler)

# ─────────────────────────────────────────────
# 🌐 5. FastAPI 서버 요청 로그 (uvicorn.access)
# ─────────────────────────────────────────────
uvicorn_access = logging.getLogger("uvicorn.access")
uvicorn_access.setLevel(logging.INFO)
uvicorn_access.propagate = False

server_handler = _daily(SERVER_LOG, logging.INFO, backup_count=5)

uvicorn_access.addHandler(server_handler)

# ─────────────────────────────────────────────
# ⚠️ 6. Uvicorn 에러 로그 (uvicorn.error)
# ─────────────────────────────────────────────
uvicorn_error = logging.getLogger("uvicorn.error")
uvicorn_error.setLevel(logging.ERROR)
uvicorn_error.propagate = False

error_handler = _daily(ERROR_LOG, logging.ERROR, backup_count=10)

# 에러는 콘솔에도 출력
error_console = logging.StreamHandler(sys.stderr)
error_console.setLevel(logging.ERROR)
error_console.setFormatter(console_formatter)

uvicorn_error.addHandler(error_handler)
uvicorn_error.addHandler(error_console)

# ─────────────────────────────────────────────
# 🧩 7. Alias (다른 파일에서 import logger 가능)
# ─────────────────────────────────────────────
logger = law11_logger

# ─────────────────────────────────────────────
# ✅ 8. 초기화 확인 메시지
# ─────────────────────────────────────────────
print(f"✅ [init] Law11 Logger initialized → {LOG_DIR}")
print(f"📄 chat_history.log / server.log / error.log 활성화 완료")
