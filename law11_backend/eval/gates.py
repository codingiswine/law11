#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
회귀 판정선과 그 근거인 실측 노이즈 (#74).

harness.py에서 떼어낸 이유는 두 가지다.

1. 테스트가 ragas를 import하지 않고 이 규칙을 검증할 수 있어야 한다.
   harness.py는 모듈 레벨에서 ragas를 import하고, ragas는 requirements-eval.txt
   전용이다(운영 의존성과 공존 불가 — #69). CI는 requirements.txt만 설치하므로
   판정선이 harness.py 안에 있으면 어떤 pytest도 이 규칙에 손을 댈 수 없다.
2. 판정선과 그 근거(실측 노이즈)가 따로 하드코딩돼 있으면 조용히 어긋난다.
   실제로 어긋났다 — 아래 MEASURED_NOISE 주석 참고.

핵심 규칙: 판정선은 상수가 아니라 MEASURED_NOISE에서 **파생**된다. 노이즈를
재측정해 아래 숫자만 바꾸면 판정선과 "판정 가능 여부"가 함께 따라온다.
"""

from typing import Dict, Set, Tuple

# ────────────────────────────────────────────
# 실측 노이즈 — 같은 설정 3회의 상대 범위 (최대-최소 ÷ 평균)
#
# 2026-11-04, 조문 1,641개 재동기화 코퍼스, 생성 gpt-4o-mini / 판정 gpt-4o-mini
# (#72). eval/results/baseline_20261104_{1747,1801,1821}_full.json 에서 재계산
# 가능하다.
#
# ⚠️ 이 표가 2026-10-19 측정(#59)에 머물러 있던 동안 판정선 3개가 노이즈보다
#    작았고, faithfulness는 실제로 오탐했다: 0.7960 → 0.6689는 −15.97%로 당시
#    판정선 0.15를 넘겨 `❌ REGRESSION` + exit 1이 났는데, 그 값은 같은 설정
#    3회 범위(0.6689~0.8135) 안이었다. 노이즈를 재측정하고 판정선을 안 고치면
#    하니스가 노이즈를 회귀로 읽는다 — tests/test_eval_gates.py가 그걸 막는다.
# ────────────────────────────────────────────
MEASURED_NOISE: Dict[str, float] = {
    "faithfulness":      0.1933,
    "answer_relevancy":  0.0159,
    "context_precision": 0.0030,
    "context_recall":    0.0110,
}
MEASURED_NOISE_DATE = "2026-11-04"
MEASURED_NOISE_RUNS = 3

# 노이즈가 0에 가까운 지표(context_precision은 0.993~0.996의 천장 근처라 0.30%)에
# 2배 규칙을 그대로 쓰면 판정선이 0.6%까지 내려가 과민해진다. 기존 주석이
# context_recall에 "0은 과민해 하한을 둔다"며 암묵적으로 쓰던 하한을 명시화한 것.
NOISE_FLOOR = 0.02

# 이보다 큰 판정선은 탐지력이 없다 — 25%를 넘는 하락만 잡는 게이트는 잡을 가치가
# 있는 변화를 거의 다 통과시킨다. 그런 지표는 느슨한 판정선을 붙여 "통과"를
# 출력하는 대신 단일 실행 판정에서 기권한다(없는 측정이 유죄도 무죄도 만들지
# 못하게). faithfulness가 여기 걸린다: 노이즈 19.33% → 2배 38.7%.
MAX_USABLE_GATE = 0.25

# 목록에 아예 없는 지표의 기본값. 위 4개는 모두 MEASURED_NOISE에 있으므로
# 지금은 쓰이지 않지만, 지표를 새로 추가하고 노이즈를 재지 않은 경우를 위해 남긴다.
REGRESSION_THRESHOLD = 0.05


def gate_for_noise(noise: float) -> float:
    """실측 노이즈 → 판정선. 노이즈의 2배, 단 NOISE_FLOOR 하한."""
    return max(2 * noise, NOISE_FLOOR)


# 판정선과 "판정 가능 여부"를 둘 다 MEASURED_NOISE에서 파생시킨다 — 단일 소스라
# 둘이 어긋날 수가 없다.
SINGLE_RUN_UNRELIABLE: Set[str] = {
    k for k, n in MEASURED_NOISE.items() if gate_for_noise(n) > MAX_USABLE_GATE
}
METRIC_THRESHOLDS: Dict[str, float] = {
    k: gate_for_noise(n)
    for k, n in MEASURED_NOISE.items()
    if k not in SINGLE_RUN_UNRELIABLE
}


def threshold_for(key: str) -> float:
    return METRIC_THRESHOLDS.get(key, REGRESSION_THRESHOLD)


def judge(key: str, before: float, after: float) -> Tuple[str, str, bool]:
    """(Δ 문자열, 아이콘, 회귀로 집계할지) 반환.

    아이콘: ✅ 개선 · ❌ 회귀 · 〰️ 판정선 안 · — 단일 실행 판정 제외 · 〰️(N/A) before=0
    """
    if before == 0:
        return "  N/A ", "〰️", False
    delta = (after - before) / before
    s = f"{'+' if delta >= 0 else ''}{delta * 100:.0f}%"
    if key in SINGLE_RUN_UNRELIABLE:
        # Δ는 보여주되 판정하지 않는다 — 노이즈가 판정 가능 범위를 넘는 지표다.
        return s, "—", False
    threshold = threshold_for(key)
    if delta > threshold:
        return s, "✅", False
    if delta < -threshold:
        return s, "❌", True
    return s, "〰️", False


def gate_legend() -> str:
    """판정선을 실제 값에서 만들어 한 줄로. 하드코딩된 '5%'가 어떤 지표에도
    적용되지 않는 숫자였던 문제(#74)를 다시 만들지 않기 위해 문구를 파생시킨다."""
    parts = [f"{k} {threshold_for(k) * 100:.1f}%" for k in sorted(METRIC_THRESHOLDS)]
    for k in sorted(SINGLE_RUN_UNRELIABLE):
        parts.append(f"{k} 판정제외(노이즈 {MEASURED_NOISE[k] * 100:.1f}%)")
    return "판정선: " + " · ".join(parts)


def regression_summary(regressed: list) -> str:
    """종합 판정 한 줄. 넘은 지표와 그 지표의 판정선을 같이 적는다."""
    if not regressed:
        if SINGLE_RUN_UNRELIABLE:
            skipped = ", ".join(sorted(SINGLE_RUN_UNRELIABLE))
            return ("  ✅ 회귀 없음 — 판정 대상 지표가 모두 판정선 안에 있습니다."
                    f" (단일 실행 판정 제외: {skipped} — --repeat 으로 확인)")
        return "  ✅ 회귀 없음 — 판정 대상 지표가 모두 판정선 안에 있습니다."
    parts = ", ".join(f"{k}(판정선 {threshold_for(k) * 100:.1f}%)" for k in regressed)
    return f"  ❌ REGRESSION 감지 — 판정선 초과: {parts}"


if __name__ == "__main__":
    print(f"실측 노이즈 ({MEASURED_NOISE_DATE}, {MEASURED_NOISE_RUNS}회):")
    for k, n in MEASURED_NOISE.items():
        g = gate_for_noise(n)
        state = "판정 제외" if k in SINGLE_RUN_UNRELIABLE else f"판정선 {g * 100:.1f}%"
        print(f"  {k:<20} {n * 100:5.2f}%  → 2배 {g * 100:5.2f}%  {state}")
    print()
    print(gate_legend())
