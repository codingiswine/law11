"""버전 단일 소스 회귀 테스트 (#51, #76).

/health 의 version 이 0.8.2 에 멈춘 채 README 배지만 1.9.x 로 올라가던 드리프트를 막는다.

아래 두 가드는 둘 다 settings.APP_VERSION 을 기준으로 삼으므로, 셋이 **나란히** 낡으면
통과한다 — 실제로 1.13.1 에 멈춘 채 마이너 세 개가 지나갔다(#76). 그래서 기준점을
저장소 바깥(CHANGELOG 최신 항목)에 두는 가드를 하나 더 둔다.
"""
import re
from pathlib import Path

from app.config import settings
from app.main import app

_ROOT = Path(__file__).resolve().parents[2]
_BADGE = re.compile(r"badge/Version-(\d+\.\d+\.\d+)-")
# 번호 헤딩에 붙은 버전 태그. 예: '### 76. ... `v1.16.4`'
_CHANGELOG_TAG = re.compile(r"^### \d+\..*`v(\d+\.\d+\.\d+)`", re.M)


def test_health_version_comes_from_settings():
    assert app.version == settings.APP_VERSION


def test_readme_badges_match_settings():
    for name in ("README.md", "README.en.md"):
        m = _BADGE.search((_ROOT / name).read_text(encoding="utf-8"))
        assert m, f"{name}: 버전 배지 없음"
        assert m.group(1) == settings.APP_VERSION, f"{name} 배지 {m.group(1)} != settings {settings.APP_VERSION}"


def test_settings_version_matches_latest_changelog_entry():
    """배지와 settings 가 같이 낡는 걸 막는다 — 기준점을 CHANGELOG 최신 항목에 둔다 (#76).

    CHANGELOG 는 항목을 추가할 때 반드시 손대는 파일이므로, 버전을 잊으면 여기서 걸린다.
    """
    tags = _CHANGELOG_TAG.findall((_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert tags, "CHANGELOG 에 버전 태그가 붙은 번호 항목이 없음"
    assert tags[-1] == settings.APP_VERSION, (
        f"CHANGELOG 최신 {tags[-1]} != settings {settings.APP_VERSION} — "
        "항목을 추가했으면 settings.APP_VERSION 과 README 배지 2곳을 함께 올릴 것"
    )
