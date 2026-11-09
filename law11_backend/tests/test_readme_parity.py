"""영문 README가 한글 README와 같은 사실을 말하는지 대조한다 (#75).

#25의 요점은 "정답지를 교정하자 Top-3 recall이 46.7% → 40.0%로 내려갔다 —
가짜 성공이 걷혔기 때문"이다. 영문판은 리랭커 제거의 성과(83.3%)를 라벨 교정에
붙여 적어, 같은 #25를 한글판과 반대 방향으로 서술하고 있었다.

#60은 건수 표기만 대조하고 서술 내용은 보지 않아 이 드리프트를 놓쳤다.
지워진 건 숫자가 아니라 발견 자체여서, 적어도 이 한 줄은 테스트로 묶는다.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DOCS = ("README.md", "README.en.md")


def _golden_set_line(text: str) -> str | None:
    """#25의 골든셋 교정 서술 줄. `(#25)`를 참조하는 줄이 여럿이라 46.7%로 특정한다."""
    hits = [ln for ln in text.splitlines() if "(#25)" in ln and "46.7%" in ln]
    return hits[0] if len(hits) == 1 else None


def test_golden_set_correction_reports_the_drop():
    missing = []
    for name in _DOCS:
        line = _golden_set_line((_ROOT / name).read_text(encoding="utf-8"))
        if line is None:
            missing.append(f"{name}: #25의 골든셋 교정 서술 줄을 특정하지 못했다")
        elif "40.0%" not in line:
            missing.append(
                f"{name}: 교정 직후의 하락(40.0%)이 빠졌다 — 교정이 점수를 올린 것처럼 읽힌다\n    {line.strip()}"
            )
    assert not missing, "README 서술이 CHANGELOG #25와 어긋난다:\n  " + "\n  ".join(missing)
