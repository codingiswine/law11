"""법령 최신화는 한 번에 하나만 돈다 (#86).

주간 cron과 수동 POST /api/admin/update-laws가 같은 run_law_update()를 부른다.
가드가 없으면 연타·겹침 시 AsyncLawUpdater 두 개가 PG upsert와 Qdrant 삭제를 섞어
돌린다. 또 엔드포인트가 Task 참조를 버려 GC·예외 미관측 위험이 있었다.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import main
from app.services import law_scheduler


class _SlowUpdater:
    """update_all이 release 이벤트를 기다리는 가짜 AsyncLawUpdater."""
    entered = 0

    def __init__(self):
        self.release = asyncio.Event()

    async def __aenter__(self):
        _SlowUpdater.entered += 1
        return self

    async def __aexit__(self, *exc):
        return False

    async def update_all(self):
        await self.release.wait()


@pytest.mark.asyncio
async def test_second_run_is_skipped_while_first_is_running():
    _SlowUpdater.entered = 0
    holder = {}

    def _factory():
        holder["u"] = _SlowUpdater()
        return holder["u"]

    with patch.object(law_scheduler, "AsyncLawUpdater", _factory):
        first = asyncio.create_task(law_scheduler.run_law_update())
        await asyncio.sleep(0)                      # first가 lock을 잡고 update_all에서 대기
        assert law_scheduler.law_update_running()

        # 가드가 없으면 두 번째 호출은 lock에서 영원히 기다린다(교착) — 실패가 아니라 멈춤이 되므로
        # 타임아웃을 건다. 실측: 가드를 빼고 돌리자 pytest가 300초를 넘겨 멈췄다.
        second = await asyncio.wait_for(law_scheduler.run_law_update(), timeout=1)
        assert second is False, "실행 중인데 두 번째가 들어갔다"
        assert _SlowUpdater.entered == 1, "AsyncLawUpdater가 두 번 만들어졌다"

        holder["u"].release.set()
        assert await first is True
        assert not law_scheduler.law_update_running()


@pytest.mark.asyncio
async def test_endpoint_rejects_with_409_while_running_and_keeps_the_task():
    gate = asyncio.Event()

    async def _slow_update():
        await gate.wait()
        return True

    with patch.object(law_scheduler, "run_law_update", _slow_update), \
         patch.object(law_scheduler, "law_update_running", lambda: False):
        first = await main.trigger_law_update()
    assert first["status"] == "started"
    assert isinstance(main.app.state.law_update_task, asyncio.Task), "Task 참조를 들고 있지 않다"
    assert not main.app.state.law_update_task.done()

    with patch.object(law_scheduler, "law_update_running", lambda: True):
        with pytest.raises(HTTPException) as e:
            await main.trigger_law_update()
    assert e.value.status_code == 409

    gate.set()
    assert await main.app.state.law_update_task is True
