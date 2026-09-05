import secrets
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.config import settings
from app.services.law_scheduler import start_scheduler, stop_scheduler
from core.logger import *


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Law11 FastAPI Backend",
    description="GPT-4o 기반 Adaptive Streaming 챗봇 백엔드",
    version="0.8.2",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    return """
    <!DOCTYPE html>
    <html><head><title>Law11 Backend</title></head>
    <body>
        <h1>Law11 FastAPI Backend is running!</h1>
        <p>Visit <a href="/docs">/docs</a> for API documentation.</p>
    </body></html>
    """


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": app.version}


def require_admin_key(x_admin_key: str = Header(None)):
    """관리자 엔드포인트 인증 — X-Admin-Key 헤더를 ADMIN_API_KEY와 대조.

    ⚠️ 이 엔드포인트들은 법령 전체 재수집(OpenAI 임베딩 수천 건)과 chat_history
    덤프를 트리거한다. 백엔드는 프론트에 서비스해야 하므로 0.0.0.0:8000으로 열리고,
    EC2에 올리면 보안 그룹이 유일한 방어선이 된다 — #31/#9d9c230과 같은 계열의
    노출이라 인증을 붙였다.

    키 미설정 시 통과가 아니라 503으로 막는다(fail-closed). 비교는
    secrets.compare_digest로 상수 시간 처리해 타이밍 공격을 피한다.
    """
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="관리자 엔드포인트가 비활성화돼 있습니다 (ADMIN_API_KEY 미설정).",
        )
    if not x_admin_key or not secrets.compare_digest(x_admin_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="관리자 인증에 실패했습니다.")


@app.post("/api/admin/update-laws", tags=["admin"], dependencies=[Depends(require_admin_key)])
async def trigger_law_update():
    """법령 즉시 최신화 (수동 트리거)"""
    from app.services.law_scheduler import run_law_update
    import asyncio
    asyncio.create_task(run_law_update())
    return {"status": "started", "message": "법령 최신화가 백그라운드에서 시작됐습니다."}


@app.post("/api/admin/backup-chat-history", tags=["admin"], dependencies=[Depends(require_admin_key)])
async def trigger_chat_backup():
    """chat_history 즉시 백업 (수동 트리거)"""
    from app.services.backup_service import backup_chat_history
    path = await backup_chat_history()
    return {"status": "done", "path": str(path)}
