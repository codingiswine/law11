"""버전 단일 소스 회귀 테스트 (#51).

/health 의 version 이 0.8.2 에 멈춘 채 README 배지만 1.9.x 로 올라가던 드리프트를 막는다.
"""
import re
from pathlib import Path

from app.config import settings
from app.main import app

_ROOT = Path(__file__).resolve().parents[2]
_BADGE = re.compile(r"badge/Version-(\d+\.\d+\.\d+)-")


def test_health_version_comes_from_settings():
    assert app.version == settings.APP_VERSION


def test_readme_badges_match_settings():
    for name in ("README.md", "README.en.md"):
        m = _BADGE.search((_ROOT / name).read_text(encoding="utf-8"))
        assert m, f"{name}: 버전 배지 없음"
        assert m.group(1) == settings.APP_VERSION, f"{name} 배지 {m.group(1)} != settings {settings.APP_VERSION}"
