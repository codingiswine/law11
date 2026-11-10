#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
harness.py — Law11 Eval Harness v1.0
──────────────────────────────────────────────────────────────
베이스라인 측정 + 회귀 테스트 + smoke test 를 하나의 진입점으로 통합.

실행:
    cd law11_backend
    source .venv/bin/activate

    python -m eval.harness              # 전체 평가 (30개) + 직전 결과와 자동 비교
    python -m eval.harness --smoke      # 빠른 확인 (5개)
    python -m eval.harness --compare    # 새 실행 없이 직전 두 결과만 비교
"""

import sys
import json
import asyncio
import argparse
from collections import Counter
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from eval.retriever import retrieve_and_generate

# RAGAS
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
from ragas.run_config import RunConfig
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from datasets import Dataset

# ⚠️ ragas==0.1.21의 Prompt.format()이 json.dumps(value)를 ensure_ascii=True
# (기본값)로 호출해 한국어 입력이 \uXXXX 이스케이프로 깨진 채 LLM에 전달됨을
# 실측 확인(2026-09-05) — GPT가 "산업안전보건법 제17조"를 미국 수정헌법
# 17조로 착각해 답변하는 등 완전히 무관한 내용을 만들어냈다(faithfulness의
# statements 추출 단계, answer_relevancy의 질문 생성 단계 모두 동일 경로).
# Prompt.format을 ensure_ascii=False로 고쳐 몽키패치한다 — 라이브러리
# 업그레이드는 API가 많이 바뀌어 위험이 크고, 이 메서드 하나만 국소
# 교체하는 게 가장 작은 개입이다. 원본 로직(ragas/llms/prompt.py)과
# 100% 동일, json.dumps 호출의 ensure_ascii 인자만 다르다.
import json as _json
from ragas.llms.prompt import Prompt as _Prompt, PromptValue as _PromptValue


def _patched_format(self, **kwargs):
    if set(self.input_keys) != set(kwargs.keys()):
        raise ValueError(
            f"Input variables {self.input_keys} do not match with the given parameters {list(kwargs.keys())}"
        )
    for key, value in kwargs.items():
        if isinstance(value, str):
            kwargs[key] = _json.dumps(value, ensure_ascii=False)
    prompt = self.to_string()
    return _PromptValue(prompt_str=prompt.format(**kwargs))


_Prompt.format = _patched_format

# ────────────────────────────────────────────
# 경로
# ────────────────────────────────────────────
EVAL_DIR        = Path(__file__).parent
GOLDEN_PATH     = EVAL_DIR / "golden_dataset.json"
RESULTS_DIR     = EVAL_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

SMOKE_SIZE      = 5

# 회귀 판정선은 eval/gates.py가 실측 노이즈에서 파생한다 (#74). 여기서 떼어낸 이유는
# 그 파일 docstring에 있다 — 요지는 ragas 없이 테스트할 수 있어야 한다는 것.
from eval.gates import (
    METRIC_THRESHOLDS,
    REGRESSION_THRESHOLD,
    SINGLE_RUN_UNRELIABLE,
    MEASURED_NOISE,
    MEASURED_NOISE_DATE,
    MEASURED_NOISE_RUNS,
    judge,
    threshold_for,
    gate_legend,
    regression_summary,
)

# ────────────────────────────────────────────
# RAGAS 설정 — 판정기는 settings.JUDGE_MODEL(기본 gpt-4o-mini)로 고정한다.
# 생성 모델(LLM_MODEL)과 같은 값을 쓰면 모델을 바꿀 때 채점자도 같이 바뀌어
# 점수 변화의 원인을 생성/채점으로 분리할 수 없다 (#57).
# ────────────────────────────────────────────
_ragas_llm = LangchainLLMWrapper(
    ChatOpenAI(model=settings.JUDGE_MODEL, api_key=settings.OPENAI_API_KEY)
)
_ragas_emb = LangchainEmbeddingsWrapper(
    OpenAIEmbeddings(model=settings.EMBEDDING_MODEL, api_key=settings.OPENAI_API_KEY)
)
for _m in [faithfulness, answer_relevancy, context_precision, context_recall]:
    _m.llm = _ragas_llm
answer_relevancy.embeddings = _ragas_emb

# answer_relevancy는 2026-09-04에 한 차례 제외했었다 (noncommittal 오분류로
# 점수가 0에 수렴) — 원인을 더 파보니 위 _patched_format 몽키패치와 근본
# 원인이 같았다(한국어가 \uXXXX로 깨져 GPT가 못 읽음). 몽키패치 적용 후
# noncommittal 오분류가 재현되지 않는 것을 직접 확인(2026-09-05)해 복구.

METRICS_ORDER = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
METRICS_LABEL = {
    "faithfulness":      "Faithfulness",
    "answer_relevancy":  "Answer Relevancy",
    "context_precision": "Context Precision",
    "context_recall":    "Context Recall",
}

# ────────────────────────────────────────────
# 데이터셋 로드
# ────────────────────────────────────────────
def load_dataset(smoke: bool = False) -> List[Dict]:
    if not GOLDEN_PATH.exists():
        raise FileNotFoundError(
            f"골든 데이터셋 없음: {GOLDEN_PATH}\n"
            "python -m eval.seed_golden_dataset 먼저 실행하세요."
        )
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    dataset = raw["dataset"]

    if smoke:
        # 질문 유형별로 1개씩 선택해 다양성 확보
        seen_types = set()
        selected = []
        for item in dataset:
            qt = item.get("question_type", "unknown")
            if qt not in seen_types:
                seen_types.add(qt)
                selected.append(item)
            if len(selected) >= SMOKE_SIZE:
                break
        # 유형이 부족하면 앞에서 채움
        if len(selected) < SMOKE_SIZE:
            for item in dataset:
                if item not in selected:
                    selected.append(item)
                if len(selected) >= SMOKE_SIZE:
                    break
        return selected

    return dataset


# ────────────────────────────────────────────
# RAG 파이프라인 실행
# ────────────────────────────────────────────
async def run_pipeline(dataset: List[Dict]) -> List[Dict]:
    results = []
    total = len(dataset)
    for i, item in enumerate(dataset):
        q_id = item.get("id", f"#{i+1}")
        print(f"  [{i+1:02d}/{total}] {q_id} — {item['question'][:48]}...")
        try:
            out = await retrieve_and_generate(item["question"])
            results.append({
                "id":               q_id,
                "question_type":    item.get("question_type", "unknown"),
                "law_name":         item.get("law_name", ""),
                "article_number":   item.get("article_number", ""),
                "question":         out["question"],
                "answer":           out["answer"],
                "contexts":         out["contexts"],
                "ground_truth":     item["ground_truth"],
                "retrieved_articles": out["retrieved_articles"],
                "source":           out.get("source", ""),
                "status":           "success",
            })
            print(f"         contexts={len(out['contexts'])}, answer={len(out['answer'])}자")
        except Exception as e:
            print(f"         ❌ ERROR: {e}")
            results.append({
                "id": q_id, "question": item["question"],
                "answer": "", "contexts": [], "ground_truth": item.get("ground_truth", ""),
                "retrieved_articles": [], "status": "error", "error": str(e),
            })
        await asyncio.sleep(0.5)
    return results


# ────────────────────────────────────────────
# RAGAS 평가
# ────────────────────────────────────────────
def compute_ragas(pipeline_results: List[Dict]) -> Dict[str, float]:
    valid = [r for r in pipeline_results if r["status"] == "success" and r["contexts"]]
    if not valid:
        raise ValueError("평가 가능한 결과가 없습니다. retriever / Qdrant 연결을 확인하세요.")

    ds = Dataset.from_dict({
        "question":     [r["question"]     for r in valid],
        "answer":       [r["answer"]       for r in valid],
        "contexts":     [r["contexts"]     for r in valid],
        "ground_truth": [r["ground_truth"] for r in valid],
    })
    # ⚠️ RAGAS 기본 동시성(max_workers=16)이 gpt-4o-mini 조직 TPM 한도(200,000)를
    # 순식간에 넘겨 judge 호출이 대량 실패한 것을 실측 확인(2026-09-04) — 실패 시
    # RAGAS는 해당 지표를 None으로 채우고 집계에서 조용히 스킵해, "회귀"처럼
    # 보이는 가짜 저점이 나온다 (실측 사례: 당시 포함돼 있던 answer_relevancy가
    # 0.57→0.0003으로 떨어져 보였음 — 그 지표는 이후 별도 사유로 제거됨, 위 주석
    # 참고). max_workers=3도 timeout이 남아있어(실측) 순차 실행(1)으로 신뢰성을
    # 우선한다 — 회귀 확인은 자주 도는 핫패스가 아니라 느려도 괜찮다.
    # timeout 180→300: 순차 실행(max_workers=1)에서도 개별 judge 호출이 180초를
    # 넘는 경우가 실측 확인됨(2026-09-04) — 동시성과 무관한 API 응답 지연.
    score = evaluate(
        dataset=ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        run_config=RunConfig(max_workers=1, timeout=300),
    )
    df = score.to_pandas()

    # 케이스별 점수를 per_case_results에 붙인다 (#71). 집계만 저장하던 동안
    # GS-024 회귀에서 "어느 케이스가 떨어졌는가"를 추적할 수 없었다. 이미 계산된
    # 값이라 저장에 추가 LLM 호출이 없다. valid는 pipeline_results의 같은 dict
    # 객체들이므로 여기서 붙이면 save_result가 그대로 기록한다.
    rows = df.to_dict("records")
    if len(rows) != len(valid):
        raise ValueError(
            f"RAGAS 결과 {len(rows)}행 ≠ 입력 {len(valid)}건 — 케이스별 점수를 붙일 수 없다"
        )
    for case, row in zip(valid, rows):
        # 행 순서가 입력과 같다는 전제(ragas 0.1.21)를 가정으로 두지 않고 대조한다.
        # 어긋난 채 붙이면 엉뚱한 케이스를 추적하게 되므로 조용히 넘기면 안 된다.
        if row.get("question") != case["question"]:
            raise ValueError("RAGAS 결과 행 순서가 입력과 다르다 — 케이스별 점수를 붙일 수 없다")
        case["ragas_scores"] = {
            k: round(float(row[k]), 4)
            for k in METRICS_ORDER
            # NaN은 그 지표의 판정이 실패했다는 뜻이고 집계(mean)에서도 빠진다.
            # 0.0으로 저장하면 '낮은 점수'로 오독되므로 키 자체를 비워 둔다.
            if k in row and float(row[k]) == float(row[k])
        }
    return df.mean(numeric_only=True).to_dict()


# ────────────────────────────────────────────
# 결과 저장
# ────────────────────────────────────────────
def save_result(pipeline_results: List[Dict], metrics: Dict, tag: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = RESULTS_DIR / f"baseline_{ts}_{tag}.json"
    payload = {
        "run_date":         datetime.now().isoformat(),
        "harness_version":  "1.0",
        "tag":              tag,
        # 어느 모델로 생성하고 어느 모델로 채점했는지 남긴다. 둘 중 하나만 바뀌어도
        # 점수가 움직이므로, 기록이 없으면 과거 결과와 비교할 수 없다 (#57).
        "gen_model":        settings.LLM_MODEL,
        "judge_model":      settings.JUDGE_MODEL,
        "embedding_model":  settings.EMBEDDING_MODEL,
        "dataset_size":     len(pipeline_results),
        "success_count":    sum(1 for r in pipeline_results if r["status"] == "success"),
        # ⚠️ RAGAS는 조문 근거가 있는 케이스만 채점한다(compute_ragas의 contexts 필터).
        # 운영이 웹 폴백으로 넘기는 질문은 분모에서 빠지므로, 빠진 건수를 남기지
        # 않으면 "30케이스 측정"이라고 잘못 읽게 된다.
        "ragas_scored":     sum(1 for r in pipeline_results if r["status"] == "success" and r["contexts"]),
        "source_breakdown": dict(Counter(r.get("source", "") for r in pipeline_results)),
        "metrics":          metrics,
        "per_case_results": pipeline_results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return path


# ────────────────────────────────────────────
# 직전 결과 로드
# ────────────────────────────────────────────
def load_previous_results(exclude_path: Optional[Path] = None) -> Optional[Dict]:
    """results/ 에서 exclude_path 를 제외한 가장 최신 파일 반환."""
    candidates = sorted(RESULTS_DIR.glob("baseline_*.json"), reverse=True)
    for path in candidates:
        if exclude_path and path == exclude_path:
            continue
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def load_two_latest() -> Tuple[Optional[Dict], Optional[Dict]]:
    """비교 모드용: 최신 2개 로드 (before=두번째, after=첫번째)."""
    candidates = sorted(RESULTS_DIR.glob("baseline_*.json"), reverse=True)
    after, before = None, None
    if len(candidates) >= 1:
        with open(candidates[0], encoding="utf-8") as f:
            after = json.load(f)
    if len(candidates) >= 2:
        with open(candidates[1], encoding="utf-8") as f:
            before = json.load(f)
    return before, after


# ────────────────────────────────────────────
# 비교 + 출력
# ────────────────────────────────────────────
W = 47   # 총 라인 너비 (│ 포함)

def _pad(s: str, width: int) -> str:
    """유니코드 아이콘 포함 문자열을 시각 너비 기준으로 패딩."""
    # ✅ ❌ 〰️ 는 터미널에서 2칸이지만 len()은 1~2 로 다름 → 근사치 보정
    vis_extra = sum(1 for c in s if ord(c) > 0x2FFF)
    pad = width - len(s) - vis_extra
    return s + " " * max(pad, 0)


def _box_line(content: str) -> str:
    inner = W - 2  # │ 두 개 제외
    vis_extra = sum(1 for c in content if ord(c) > 0x2FFF)
    pad = inner - len(content) - vis_extra
    return f"│{content}{' ' * max(pad, 0)}│"


def print_comparison(
    before_data: Optional[Dict],
    after_data: Dict,
    run_ts: str,
) -> bool:
    """
    비교 테이블 출력. 회귀가 하나라도 있으면 True 반환.
    """
    sep_top    = "┌" + "─" * (W - 2) + "┐"
    sep_mid    = "├" + "─" * (W - 2) + "┤"
    sep_bottom = "└" + "─" * (W - 2) + "┘"

    print(sep_top)
    print(_box_line(f"  Law11 Eval Harness v1.0"))
    print(_box_line(f"  실행: {run_ts}"))

    after_metrics  = after_data.get("metrics", {})
    after_tag      = after_data.get("tag", "?")
    after_n        = after_data.get("dataset_size", "?")

    if before_data:
        before_metrics = before_data.get("metrics", {})
        before_tag     = before_data.get("tag", "?")
        before_run     = before_data.get("run_date", "")[:16]
        print(_box_line(f"  Before: {before_run} ({before_tag}, {before_data.get('dataset_size','?')}개)"))
        print(_box_line(f"  After : 방금 실행 ({after_tag}, {after_n}개)"))
        # 모델이 바뀐 비교인지 한눈에 보이게 한다 — 생성 모델이 다르면 Δ의 원인이 다르다
        b_gen, a_gen = before_data.get("gen_model", "?"), after_data.get("gen_model", "?")
        b_jdg, a_jdg = before_data.get("judge_model", "?"), after_data.get("judge_model", "?")
        print(_box_line(f"  생성 모델: {b_gen} → {a_gen}" + ("   ⚠️ 변경됨" if b_gen != a_gen else "")))
        print(_box_line(f"  판정 모델: {b_jdg} → {a_jdg}" + ("   ⚠️ 변경됨 — Δ 해석 주의" if b_jdg != a_jdg else "   (고정)")))
        print(sep_mid)
        print(_box_line(f"  {'Metric':<22} {'Before':>7}  {'After':>7}  {'Δ':>6}  "))
        print(_box_line(f"  {'─'*22}  {'─'*7}  {'─'*7}  {'─'*6}  "))

        regressed: List[str] = []
        for key in METRICS_ORDER:
            label  = METRICS_LABEL[key]
            b_val  = before_metrics.get(key)
            a_val  = after_metrics.get(key)
            if b_val is None or a_val is None:
                line = f"  {label:<22} {'N/A':>7}  {'N/A':>7}  {'N/A':>6}  "
                print(_box_line(line))
                continue
            delta_s, icon, is_regression = judge(key, b_val, a_val)
            if is_regression:
                regressed.append(key)
            line = f"  {label:<22} {b_val:>7.4f}  {a_val:>7.4f}  {delta_s:>6} {icon}"
            print(_box_line(line))
    else:
        print(_box_line(f"  (직전 결과 없음 — 이번 실행이 첫 베이스라인)"))
        print(_box_line(f"  실행: {after_tag}, {after_n}개 케이스"))
        print(sep_mid)
        print(_box_line(f"  {'Metric':<22} {'Score':>7}  {'Bar':<20}"))
        print(_box_line(f"  {'─'*22}  {'─'*7}  {'─'*20}"))

        regressed = []
        for key in METRICS_ORDER:
            label = METRICS_LABEL[key]
            val   = after_metrics.get(key)
            if val is None:
                print(_box_line(f"  {label:<22} {'N/A':>7}"))
                continue
            filled = int(val * 16)
            bar    = "█" * filled + "░" * (16 - filled)
            print(_box_line(f"  {label:<22} {val:>7.4f}  {bar}"))

    print(sep_bottom)

    # 판정선을 값에서 만들어 같이 찍는다 — 표의 ✅/❌/— 가 어느 기준으로 붙었는지
    # 로그만 보고 알 수 있어야 한다. 과거엔 종합 판정이 "5% 이상 하락"으로
    # 하드코딩돼 있었는데, 4개 지표 전부 판정선이 따로 있어서 5%는 어떤 지표에도
    # 적용되지 않는 숫자였다 (#74).
    print(f"\n  {gate_legend()}")
    print(f"  (실측 노이즈 {MEASURED_NOISE_DATE} · 같은 설정 {MEASURED_NOISE_RUNS}회 범위의 2배, 하한 2%)")

    # 종합 판정
    if before_data:
        print()
        print(regression_summary(regressed))
    print()
    return bool(regressed) if before_data else False


# ────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────
def print_repeat_summary(all_metrics: List[Dict[str, float]]) -> None:
    """같은 설정 N회 결과의 평균과 범위를 낸다.

    단일 실행 비교로는 변경의 효과와 노이즈를 구분할 수 없다. 특히 faithfulness는
    조건에 따라 노이즈가 3.4배까지 달라져(#58), 범위를 함께 보지 않으면 판정이 틀린다.
    """
    n = len(all_metrics)
    print(f"\n{'─'*61}")
    print(f"  반복 측정 요약 — 같은 설정 {n}회")
    print(f"  생성 {settings.LLM_MODEL} / 판정 {settings.JUDGE_MODEL}")
    print(f"{'─'*61}")
    print(f"  {'Metric':<20}{'평균':>9}{'최소':>9}{'최대':>9}{'범위':>9}{'상대':>8}")
    print(f"  {'─'*20}{'─'*9}{'─'*9}{'─'*9}{'─'*9}{'─'*8}")
    for k in METRICS_ORDER:
        vals = [m[k] for m in all_metrics if k in m]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        rng  = max(vals) - min(vals)
        rel  = (rng / mean * 100) if mean else 0.0
        if k in SINGLE_RUN_UNRELIABLE:
            # 노이즈가 판정 가능 범위를 넘어 단일 실행 판정에서 빠진 지표. 여기서는
            # 범위 자체가 결과물이므로 경고가 아니라 상태를 적는다.
            warn = "  (단일 실행 판정 제외)"
        else:
            gate = threshold_for(k) * 100
            warn = "  ⚠️ 판정선 초과" if rel > gate else ""
        print(f"  {k:<20}{mean:>9.4f}{min(vals):>9.4f}{max(vals):>9.4f}{rng:>9.4f}{rel:>7.2f}%{warn}")
    print(f"{'─'*61}")
    print(f"  {gate_legend()}")
    print("  다음 변경의 유의성은 위 '범위'의 2배를 넘는지로 판단한다.")
    print(f"  이 표의 '상대'가 gates.py의 MEASURED_NOISE({MEASURED_NOISE_DATE})와 크게 다르면")
    print("  그 상수를 갱신해야 한다 — 판정선이 거기서 파생되므로 함께 따라온다 (#74).\n")


async def main(smoke: bool = False, compare_only: bool = False, repeat: int = 1,
               _in_repeat: bool = False):
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── repeat 모드: 같은 설정을 N회 돌려 분산을 낸다 ──
    if repeat > 1:
        print(f"\n  [repeat 모드] 같은 설정으로 {repeat}회 측정합니다.\n")
        collected: List[Dict[str, float]] = []
        for i in range(repeat):
            print(f"\n{'='*61}\n  {i+1}/{repeat} 회차\n{'='*61}")
            await main(smoke=smoke, compare_only=False, repeat=1, _in_repeat=True)
            latest = load_previous_results(exclude_path=None)
            if latest:
                collected.append(latest["metrics"])
        if collected:
            print_repeat_summary(collected)
        return

    # ── compare-only 모드 ──────────────────────
    if compare_only:
        print("\n  [compare 모드] 저장된 결과 두 개를 비교합니다.\n")
        before, after = load_two_latest()
        if after is None:
            print("  ❌ results/ 에 결과 파일이 없습니다. 먼저 harness 를 실행하세요.")
            return
        if before is None:
            print("  ⚠️  결과가 1개뿐입니다. before 없이 after만 표시합니다.")
        print_comparison(before, after, run_ts)
        return

    # ── 평가 실행 ──────────────────────────────
    tag = "smoke" if smoke else "full"
    print(f"\n{'─'*49}")
    print(f"  Law11 Eval Harness v1.0  [{tag.upper()}]  {run_ts}")
    print(f"{'─'*49}\n")

    dataset = load_dataset(smoke=smoke)
    print(f"  골든 데이터셋: {len(dataset)}개 케이스\n")

    # Step 1: RAG 파이프라인
    print("[Step 1] RAG 파이프라인 실행 중...")
    pipeline_results = await run_pipeline(dataset)
    success_n = sum(1 for r in pipeline_results if r["status"] == "success")
    print(f"\n  완료: {success_n}/{len(dataset)}개 성공\n")

    # Step 2: RAGAS
    print("[Step 2] RAGAS 메트릭 계산 중... (약 2-3분 소요)")
    metrics = compute_ragas(pipeline_results)
    print("  완료\n")

    # Step 3: 저장
    print("[Step 3] 결과 저장 중...")
    saved_path = save_result(pipeline_results, metrics, tag)
    print(f"  → {saved_path}\n")

    # repeat 회차 안에서는 직전 비교를 건너뛴다 (#70).
    # 회차끼리 비교하면 노이즈를 노이즈와 맞대는 셈이고, 직전이 smoke(5개)면
    # 크기가 다른 집합을 비교한다. repeat의 목적은 N회를 모아 범위를 내는 것이므로
    # 판정은 print_repeat_summary가 맡는다.
    if _in_repeat:
        print("[Step 4] (repeat 회차 — 직전 비교 생략)\n")
        return

    # Step 4: 직전 결과와 비교
    print("[Step 4] 직전 결과와 비교...\n")
    before_data = load_previous_results(exclude_path=saved_path)
    after_data  = {"metrics": metrics, "tag": tag,
                   "dataset_size": len(pipeline_results),
                   "run_date": run_ts,
                   # 저장 파일(save_result)과 같은 값을 넣는다 — 빠지면 비교 헤더에 "?"로 뜬다
                   "gen_model": settings.LLM_MODEL,
                   "judge_model": settings.JUDGE_MODEL}

    has_regression = print_comparison(before_data, after_data, run_ts)

    # smoke 모드 안내
    if smoke:
        print("  ⚠️  smoke 모드 (5개). 전체 평가는 python -m eval.harness 실행.")
        print()

    # 회귀 시 exit code 1 (CI 연동용)
    if has_regression:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Law11 Eval Harness v1.0")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=f"골든 데이터셋에서 {SMOKE_SIZE}개만 빠르게 실행",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="새 실행 없이 results/ 의 직전 두 파일만 비교",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="같은 설정으로 N회 측정하고 평균·범위를 출력 (노이즈 기준선 측정용)",
    )
    args = parser.parse_args()
    asyncio.run(main(smoke=args.smoke, compare_only=args.compare, repeat=args.repeat))
