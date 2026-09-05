#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_service.py
──────────────────
chat_history 테이블을 주기적으로 JSON 파일로 백업한다.

pg_dump 바이너리(postgres-client)를 앱 컨테이너에 새로 설치하지 않기 위해
SQLAlchemy로 직접 SELECT해 JSON으로 직렬화하는 방식을 쓴다 — 이미 이
컨테이너가 DB 접속 정보를 다 갖고 있어 별도 인증/네트워크 설정이 필요
없다.

스케줄링: app/services/law_scheduler.py의 daily_chat_backup job
수동 트리거: POST /api/admin/backup-chat-history (main.py)
"""

import json
from datetime import datetime, date
from pathlib import Path

from sqlalchemy import text

from app.config import settings
from core.logger import law11_logger as logger

BACKUP_DIR = Path("/app/backups") if Path("/app").exists() else Path("backups")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

RETENTION_COUNT = 30  # 하루 1회 백업 기준 약 한 달치 보관


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


async def backup_chat_history() -> Path:
    """chat_history 전체를 JSON으로 덤프하고, 오래된 백업은 정리한다."""
    async with settings.async_engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT id, session_id, turn_index, role, content, user_id,
                   metadata, score, feedback, created_at, updated_at
            FROM chat_history
            ORDER BY id
        """))
        rows = [dict(r._mapping) for r in result.fetchall()]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = BACKUP_DIR / f"chat_history_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=_json_default)

    logger.info(f"[Backup] chat_history 백업 완료: {len(rows)}건 → {path}")
    _prune_old_backups()
    return path


def _prune_old_backups(keep: int = RETENTION_COUNT) -> None:
    backups = sorted(BACKUP_DIR.glob("chat_history_*.json"), reverse=True)
    for old in backups[keep:]:
        old.unlink()
        logger.info(f"[Backup] 오래된 백업 삭제: {old.name}")
