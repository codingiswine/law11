#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
law_scheduler.py
────────────────
매주 월요일 새벽 3시, 법제처 API에서 최신 법령을 가져와
PostgreSQL + Qdrant를 자동 최신화한다.

FastAPI lifespan에서 start/stop된다.
수동 트리거: POST /api/admin/update-laws
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger("law_scheduler")

# law_updater_async.py가 law11_backend/app/tools/ 아래에 있음
BACKEND_ROOT = Path(__file__).parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.tools.law_updater_async import AsyncLawUpdater

_scheduler: Optional[AsyncIOScheduler] = None


async def run_law_update():
    """법령 최신화 실행 — 스케줄러 & 수동 트리거 공용"""
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"[LawScheduler] 법령 최신화 시작: {started_at}")
    try:
        async with AsyncLawUpdater() as updater:
            await updater.update_all()
        logger.info("[LawScheduler] 법령 최신화 완료")
    except Exception as e:
        logger.error(f"[LawScheduler] 법령 최신화 실패: {e}")
        raise


def start_scheduler():
    """FastAPI lifespan 시작 시 호출"""
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    # 매주 월요일 새벽 3시
    _scheduler.add_job(
        run_law_update,
        trigger="cron",
        day_of_week="mon",
        hour=3,
        minute=0,
        id="weekly_law_update",
        replace_existing=True,
        misfire_grace_time=3600,  # 1시간 내 지연 허용
    )

    _scheduler.start()
    next_run = _scheduler.get_job("weekly_law_update").next_run_time
    logger.info(f"[LawScheduler] 스케줄러 시작 — 다음 실행: {next_run}")


def stop_scheduler():
    """FastAPI lifespan 종료 시 호출"""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[LawScheduler] 스케줄러 종료")
