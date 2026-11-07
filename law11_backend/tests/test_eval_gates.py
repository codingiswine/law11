"""
회귀 판정선이 실측 노이즈 아래로 내려가지 않는지 지킨다 (#74).

판정선이 노이즈보다 작으면 하니스가 노이즈를 회귀로 읽는다. 가정이 아니라
2026-11-04에 실제로 일어났다(#72): faithfulness가 0.7960 → 0.6689로 −15.97%,
당시 판정선 0.15를 넘겨 `❌ REGRESSION` + exit 1이 났는데 그 값은 같은 설정
3회 범위(0.6689~0.8135) 안이었다.

eval.gates만 import한다 — eval.harness는 모듈 레벨에서 ragas를 쓰고 ragas는
requirements-eval.txt 전용이라(#69) CI의 requirements.txt 환경에서 import되지
않는다. 판정선을 gates.py로 떼어낸 이유가 이것이다.
"""
import pytest

from eval.gates import (
    MEASURED_NOISE,
    METRIC_THRESHOLDS,
    SINGLE_RUN_UNRELIABLE,
    MAX_USABLE_GATE,
    NOISE_FLOOR,
    gate_for_noise,
    gate_legend,
    judge,
    regression_summary,
    threshold_for,
)

# #72의 3회 실측 (eval/results/baseline_20261104_{1747,1801,1821}_full.json).
# 1747이 직전(1723, 0.7960) 대비 -16%로 찍혀 하니스가 회귀로 오탐한 값이다.
FAITHFULNESS_RUNS = [0.6689, 0.7604, 0.8135]
FAITHFULNESS_PREV = 0.7960


@pytest.mark.parametrize("metric", sorted(MEASURED_NOISE))
def test_gate_is_above_measured_noise(metric):
    """판정 대상 지표는 판정선이 실측 노이즈보다 반드시 커야 한다.

    이게 깨지면 같은 설정 재실행만으로 회귀가 찍힌다 — 하니스가 측정하는 대상이
    변경의 효과가 아니라 자기 노이즈가 된다.
    """
    if metric in SINGLE_RUN_UNRELIABLE:
        pytest.skip(f"{metric}은 단일 실행 판정 제외")
    noise = MEASURED_NOISE[metric]
    gate = threshold_for(metric)
    assert gate > noise, (
        f"{metric}: 판정선 {gate:.4f} <= 실측 노이즈 {noise:.4f} — "
        f"노이즈만으로 회귀가 찍힌다. gates.MEASURED_NOISE를 갱신했으면 "
        f"판정선은 거기서 파생되므로 따라온다; 수동으로 낮췄다면 되돌릴 것."
    )


@pytest.mark.parametrize("metric", sorted(MEASURED_NOISE))
def test_unusable_gate_is_excluded_not_loosened(metric):
    """노이즈가 커서 판정선이 MAX_USABLE_GATE를 넘는 지표는 느슨한 판정선을 붙여
    '통과'를 출력하는 대신 판정에서 기권해야 한다.

    38% 하락만 잡는 게이트는 잡을 가치가 있는 변화를 거의 다 통과시키므로,
    '회귀 없음'이 측정했다는 뜻으로 읽히는 게 더 위험하다.
    """
    unusable = gate_for_noise(MEASURED_NOISE[metric]) > MAX_USABLE_GATE
    assert unusable == (metric in SINGLE_RUN_UNRELIABLE), (
        f"{metric}: 판정선 {gate_for_noise(MEASURED_NOISE[metric]):.4f}, "
        f"상한 {MAX_USABLE_GATE} — 제외 여부({metric in SINGLE_RUN_UNRELIABLE})와 어긋남"
    )
    if unusable:
        assert metric not in METRIC_THRESHOLDS, (
            f"{metric}이 판정 제외인데 METRIC_THRESHOLDS에도 남아 있다"
        )


def test_faithfulness_noise_pair_is_not_a_regression():
    """#72에서 실제로 오탐한 쌍이 더는 회귀로 찍히지 않는다."""
    _, icon, is_regression = judge("faithfulness", FAITHFULNESS_PREV, min(FAITHFULNESS_RUNS))
    assert not is_regression, (
        f"0.7960 → {min(FAITHFULNESS_RUNS)} 는 같은 설정 3회 범위 "
        f"({min(FAITHFULNESS_RUNS)}~{max(FAITHFULNESS_RUNS)}) 안인데 회귀로 찍혔다"
    )
    assert icon == "—", f"판정 제외 지표의 아이콘은 — 여야 한다, got {icon}"


def test_faithfulness_full_measured_range_never_fires():
    """3회 실측의 어떤 조합도 회귀가 되지 않아야 한다 — 범위 안의 값끼리는
    모두 같은 분포에서 나온 것이므로."""
    for before in FAITHFULNESS_RUNS + [FAITHFULNESS_PREV]:
        for after in FAITHFULNESS_RUNS + [FAITHFULNESS_PREV]:
            _, _, is_regression = judge("faithfulness", before, after)
            assert not is_regression, f"{before} → {after} 가 회귀로 찍혔다"


@pytest.mark.parametrize("metric", sorted(METRIC_THRESHOLDS))
def test_judged_metrics_still_catch_a_real_drop(metric):
    """mutation 역방향: 판정 대상 지표는 판정선의 2배 하락을 반드시 잡는다.

    노이즈 기준으로 판정선을 올린 것이 '아무것도 안 잡는 하니스'가 되지 않았음을
    확인한다 — 이 테스트가 없으면 #74의 수정이 탐지력을 조용히 없앨 수 있다.
    """
    gate = threshold_for(metric)
    before = 0.80
    after = before * (1 - 2 * gate)
    _, icon, is_regression = judge(metric, before, after)
    assert is_regression, f"{metric}: {before} → {after:.4f} (판정선 {gate:.3f}의 2배)를 놓쳤다"
    assert icon == "❌"


@pytest.mark.parametrize("metric", sorted(METRIC_THRESHOLDS))
def test_judged_metrics_tolerate_their_own_noise(metric):
    """반대 방향: 자기 실측 노이즈만큼의 하락은 회귀가 아니다."""
    noise = MEASURED_NOISE[metric]
    before = 0.80
    _, _, is_regression = judge(metric, before, before * (1 - noise))
    assert not is_regression, f"{metric}: 실측 노이즈({noise:.4f})만큼의 하락이 회귀로 찍혔다"


def test_at_least_one_metric_is_still_judged():
    """판정 대상이 전부 빠지면 하니스는 아무것도 잡지 못하면서 '회귀 없음'을
    출력한다. MAX_USABLE_GATE나 NOISE_FLOOR를 과하게 올리면 그렇게 된다."""
    assert METRIC_THRESHOLDS, (
        "판정 대상 지표가 하나도 없다 — 하니스가 회귀를 탐지하지 않는다. "
        "MAX_USABLE_GATE / NOISE_FLOOR 를 확인할 것."
    )


def test_noise_floor_applies_to_near_zero_noise():
    """노이즈가 0에 가까워도 판정선은 하한 아래로 내려가지 않는다 — 천장 근처
    지표(context_precision 0.993~0.996)가 과민해지는 것을 막는다."""
    assert gate_for_noise(0.0) == NOISE_FLOOR
    assert gate_for_noise(0.0001) == NOISE_FLOOR
    assert threshold_for("context_precision") == NOISE_FLOOR


def test_summary_quotes_the_real_gate_not_a_hardcoded_number():
    """종합 판정 문구가 판정선을 값에서 만든다.

    과거엔 "5% 이상 하락한 메트릭이 있습니다"로 하드코딩돼 있었는데, 4개 지표
    전부 판정선이 따로 있어 5%는 어떤 지표에도 적용되지 않는 숫자였다.
    """
    line = regression_summary(["context_recall"])
    assert "5%" not in line
    assert f"{threshold_for('context_recall') * 100:.1f}%" in line

    clean = regression_summary([])
    assert "회귀 없음" in clean
    # 판정에서 빠진 지표가 있으면 그 사실이 '회귀 없음'과 같은 줄에 있어야 한다.
    for metric in SINGLE_RUN_UNRELIABLE:
        assert metric in clean


def test_legend_lists_every_metric():
    """범례에 판정 대상과 판정 제외가 모두 나온다 — 로그만 보고 ✅/❌/— 의
    기준을 알 수 있어야 한다."""
    legend = gate_legend()
    for metric in MEASURED_NOISE:
        assert metric in legend, f"{metric}이 범례에 없다"


# ────────────────────────────────────────────
# MEASURED_NOISE 자체가 최신인지
#
# 위 테스트들은 판정선과 노이즈 상수가 서로 어긋나지 않음을 지킨다. 그런데 상수
# 자체가 낡으면 둘이 일관되게 틀린다 — 실제로 #59(10-19)의 노이즈 표가 #72(11-04)
# 재측정 후에도 그대로 남아 있었다. 그래서 상수를 그 근거인 결과 파일에서 다시
# 계산해 맞춰본다.
# ────────────────────────────────────────────
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "eval" / "results"

# #72의 반복 측정 3회. 커밋돼 있어야 MEASURED_NOISE가 재현 가능하다
# (results/*.json은 .gitignore 대상이라 이 셋만 force-add 했다).
NOISE_BASIS_FILES = [
    "baseline_20261104_1747_full.json",
    "baseline_20261104_1801_full.json",
    "baseline_20261104_1821_full.json",
]


def _load_basis_metrics():
    paths = [RESULTS_DIR / name for name in NOISE_BASIS_FILES]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"노이즈 근거 파일 없음: {missing}")
    return [json.loads(p.read_text(encoding="utf-8"))["metrics"] for p in paths]


@pytest.mark.parametrize("metric", sorted(MEASURED_NOISE))
def test_measured_noise_matches_its_basis_files(metric):
    """MEASURED_NOISE가 근거로 적은 결과 파일에서 실제로 나오는 값인가.

    이게 깨지면 노이즈를 재측정했는데 상수를 안 고친 것이다 — 판정선이 그 상수에서
    파생되므로 판정선도 같이 낡는다. 허용 오차는 반올림분(0.5%p)만 둔다.
    """
    runs = _load_basis_metrics()
    vals = [m[metric] for m in runs]
    mean = sum(vals) / len(vals)
    actual = (max(vals) - min(vals)) / mean
    assert abs(actual - MEASURED_NOISE[metric]) < 0.005, (
        f"{metric}: 상수 {MEASURED_NOISE[metric]:.4f} vs 근거 파일 재계산 {actual:.4f} — "
        f"gates.MEASURED_NOISE를 갱신할 것 (판정선은 거기서 파생되므로 함께 따라온다)"
    )
