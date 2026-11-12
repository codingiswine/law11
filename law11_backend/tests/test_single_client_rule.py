"""외부 클라이언트는 settings.py에서만 만든다 (CLAUDE.md 설정 변경 규칙, #88).

question_router가 AsyncOpenAI를 따로 만들어 쓰고 있었다 — project 스코프와 타임아웃이
빠진 두 번째 클라이언트. 규칙은 CLAUDE.md에만 있고 확인하는 코드가 없어서 그대로
살아 있었다. 여기서는 (1) app/·core/ 어디에도 생성자 호출이 없는지 소스를 훑고,
(2) 라우터의 LLM 분류가 실제로 settings.openai_client를 타며 타임아웃을 넘기는지 본다.
"""
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.services import question_router

_BACKEND = Path(__file__).resolve().parents[1]
_CTOR = re.compile(r"\b(AsyncOpenAI|AsyncQdrantClient|QdrantClient|create_async_engine)\(")

# 알려진 예외 — 두 업데이터는 요청 경로가 아니라 주간 배치다. 실행마다 자기 클라이언트를
# 열고 닫으며(컨텍스트 매니저), Qdrant는 일괄 upsert용으로 timeout=120의 **동기** 클라이언트를
# 쓴다. settings.*로 옮기면 주간 작업의 수명 주기를 다시 설계해야 해서 #88 범위 밖으로 뒀다.
_KNOWN_BATCH_EXCEPTIONS = {"law_updater_async.py", "case_law_updater_async.py"}


def test_no_module_outside_settings_constructs_a_client():
    offenders = []
    for py in list((_BACKEND / "app").rglob("*.py")) + list((_BACKEND / "core").rglob("*.py")):
        if py.name == "settings.py" or py.name in _KNOWN_BATCH_EXCEPTIONS:
            continue
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if _CTOR.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{py.relative_to(_BACKEND)}:{lineno}: {line.strip()}")
    assert not offenders, "settings 밖에서 클라이언트를 만들고 있다:\n  " + "\n  ".join(offenders)


@pytest.mark.asyncio
async def test_router_llm_classification_uses_the_shared_client_with_timeout():
    question_router._llm_cache.clear()
    create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="news_tool"))]))
    with patch.object(settings, "openai_client",
                      SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))):
        assert await question_router._classify_with_llm("비계 사고 뉴스", "") == "news_tool"
    assert create.await_count == 1, "settings.openai_client를 타지 않았다"
    assert create.await_args.kwargs.get("timeout") == settings.GPT_TIMEOUT_SECONDS, "라우터 호출에 타임아웃이 없다"
