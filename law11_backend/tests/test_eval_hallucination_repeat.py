"""반복 판정 집계가 '매회 지적'과 '회차마다 뒤집힘'을 구분하는지 지킨다 (#77).

#72에서 이 구분이 실제로 판단을 갈랐다. GS-024는 3/3 반복됐고 조문과 대조하니
실제 결함이었지만, GS-004도 똑같이 3/3 반복됐고 대조하니 오탐이었다. 반복성은
신호일 뿐이므로, 집계는 '율'이 아니라 케이스별 이력을 내야 한다.

eval.eval_hallucination은 ragas를 import하지 않으므로(판정이 자체 LLM-judge다)
CI의 requirements.txt 환경에서 그대로 import된다 — harness와 달리 테스트 가능하다.
"""
import pytest

from eval.eval_hallucination import _out_suffix, summarize_repeat


def test_negative_controls_do_not_overwrite_the_baseline_report():
    """음성 대조군 실행이 본 리포트를 덮어쓰면 README 수치가 조작 답변 판정 결과가 된다 (#78)."""
    assert _out_suffix("eval/judge_negative_controls.json") == "_judge_negative_controls"
    assert _out_suffix("eval/results/baseline_20261104_1821_full.json") == ""
    assert _out_suffix(None) == ""


def _run(**verdicts):
    return [{"id": i, "verdict": v} for i, v in verdicts.items()]


def test_stable_grounded_runs_flag_nothing():
    runs = [_run(GS001="GROUNDED", GS002="GROUNDED") for _ in range(3)]
    s = summarize_repeat(runs)
    assert s["runs"] == 3
    assert s["always_flagged"] == [] and s["flipped"] == []


def test_always_flagged_is_separated_from_flipped():
    runs = [
        _run(GS004="PARTIAL", GS016="GROUNDED", GS024="HALLUCINATION"),
        _run(GS004="PARTIAL", GS016="PARTIAL",  GS024="HALLUCINATION"),
        _run(GS004="PARTIAL", GS016="GROUNDED", GS024="PARTIAL"),
    ]
    s = summarize_repeat(runs)

    # 매회 GROUNDED가 아닌 케이스 = 조문 대조 대상. GS-024는 판정이 바뀌었어도
    # 한 번도 GROUNDED가 아니었으므로 둘 다에 들어간다.
    assert s["always_flagged"] == ["GS004", "GS024"]
    # 회차마다 판정이 달라진 케이스 = 판정기 불안정. GS-004는 안정적으로 지적됐다.
    assert s["flipped"] == ["GS016", "GS024"]
    assert s["per_case"]["GS016"] == ["GROUNDED", "PARTIAL", "GROUNDED"]
    assert s["verdict_counts"][1] == {"PARTIAL": 2, "HALLUCINATION": 1}


def test_different_case_sets_are_not_compared():
    runs = [_run(GS001="GROUNDED"), _run(GS002="GROUNDED")]
    with pytest.raises(ValueError):
        summarize_repeat(runs)
