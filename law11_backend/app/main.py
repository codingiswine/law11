from contextlib import asynccontextmanager
from fastapi import FastAPI
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
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:5173", "http://localhost:5174", "http://localhost:5177",
        "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5177"
    ],
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


@app.post("/api/admin/update-laws", tags=["admin"])
async def trigger_law_update():
    """법령 즉시 최신화 (수동 트리거)"""
    from app.services.law_scheduler import run_law_update
    import asyncio
    asyncio.create_task(run_law_update())
    return {"status": "started", "message": "법령 최신화가 백그라운드에서 시작됐습니다."}
