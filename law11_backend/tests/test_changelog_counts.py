"""changelog 건수 표기 드리프트 회귀 테스트 (#60).

#53에서 "건수 참조 지점은 README 3곳·README.en 4곳·CHANGELOG 헤더 1곳"으로
확정했지만 그 목록을 확인하는 절차가 없어, #57~#59를 추가했을 때 또 전부
옛 숫자로 남았다(63건/56). 사람이 기억하는 대신 CHANGELOG 헤딩을 세서 대조한다.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_changelog_counts_match_docs():
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    numbered = len(re.findall(r"^### \d+\.", changelog, re.M))   # #1~#N
    patches = len(re.findall(r"^### P\d+\.", changelog, re.M))   # P1~P7 (체계 도입 이전)
    total = numbered + patches
    assert numbered and patches, f"헤딩 파싱 실패: numbered={numbered} patches={patches}"

    # #53에서 확정한 참조 지점 8곳. 한국어는 합계(total), 영문은 "plus N"을 따로 쓰므로 numbered.
    expected = {
        "CHANGELOG.md": [f"#1~#{numbered}"],
        "README.md": [
            f"changelog {total}건",
            f"{total}건을 기록했습니다",
            f"changelog {numbered}건 + 체계 도입 이전 {patches}건",
        ],
        "README.en.md": [
            f"{numbered} documented find-fix cycles",
            f"{numbered} changelog entries",
            f"documents {numbered} find-fix cycles",
            f"#1–#{numbered}",
        ],
    }

    missing = [
        f"{name}: {text!r}"
        for name, texts in expected.items()
        for text in texts
        if text not in (_ROOT / name).read_text(encoding="utf-8")
    ]
    assert not missing, (
        f"CHANGELOG 헤딩 {numbered} + P{patches} = {total}건과 어긋난 표기:\n  "
        + "\n  ".join(missing)
    )
