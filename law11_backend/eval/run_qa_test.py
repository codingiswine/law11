#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_qa_test.py
──────────────
Law11 API에 실제 요청을 보내 QA 테스트셋을 평가.
SSE 스트림을 직접 파싱해 text 청크를 수집한다.

실행:
    python eval/run_qa_test.py
"""

import json
import time
import sys
import requests
from collections import defaultdict
from datetime import datetime
from pathlib import Path

API_URL = "http://localhost:8000/api/ask"
USER_ID = "test_runner"

TEST_CASES = [
    # =========================
    # 1. 조회형 (Exact Match)
    # =========================
    {
        "query": "산업안전보건법 시행령 제2조 뭐야?",
        "type": "lookup",
        "expected_source": "pg",
        "must_contain": ["제2조"],
    },
    {
        "query": "산업안전보건기준에 관한 규칙 제52조 알려줘",
        "type": "lookup",
        "expected_source": "pg",
        "must_contain": ["제52조"],
    },
    {
        "query": "제26조 내용 뭐야?",
        "type": "lookup",
        "expected_behavior": "ask_for_law_name",
    },

    # =========================
    # 2. 판단형 (Reasoning)
    # =========================
    {
        # 산업 현장 맥락 명시 → 산안기준규칙 적용 유도
        "query": "공장 건물에 균열이 생겼는데 사업주가 뭘 해야 해?",
        "type": "reasoning",
        "expected_behavior": "conditional_answer",
        "reasoning_required": True,
    },
    {
        # 계단 흔들림 → 산안기준규칙 제26조(강도) 또는 제28조(난간) 기대
        "query": "공장 계단이 흔들리면 위험한가?",
        "type": "reasoning",
        "expected_article": ["26조", "28조", "계단"],
        "reasoning_required": True,
    },
    {
        "query": "높은 계단은 어떻게 만들어야 해?",
        "type": "reasoning",
        "expected_article": ["26조", "28조"],
        "reasoning_required": True,
    },

    # =========================
    # 3. 애매한 질문
    # =========================
    {
        "query": "오래된 건물 안전 기준 뭐야?",
        "type": "ambiguous",
        "expected_behavior": "condition_explanation",
    },
    {
        "query": "계단 규정 알려줘",
        "type": "ambiguous",
        "expected_behavior": "scope_explanation",
    },

    # =========================
    # 4. 실패 유도
    # =========================
    {
        "query": "산업안전보건법 제999조 뭐야?",
        "type": "invalid",
        "expected_behavior": "not_exist",
    },
    {
        "query": "없는 법 알려줘",
        "type": "invalid",
        "expected_behavior": "refuse",
    },

    # =========================
    # 5. fallback 테스트
    # =========================
    {
        # 외국 법령 → 웹으로 가야 함 (OSHA = 미국 기관)
        "query": "미국 OSHA 계단 규정 뭐야?",
        "type": "fallback",
        "expected_source": "web",
    },
    {
        # "최신 개정" → DB 정보가 오래됐을 수 있으므로 웹 검색 필요
        "query": "2025년에 바뀐 산업안전보건법 내용 알려줘",
        "type": "fallback",
        "expected_source": "web",
    },

    # =========================
    # 6. 킬러 테스트 (중요)
    # =========================
    {
        "query": "계단이 오래됐는데 무조건 안전진단 해야 돼?",
        "type": "trap",
        "expected_behavior": "conditional_answer",
    },
    {
        "query": "균열 없는 건물도 안전성 평가 해야 하나?",
        "type": "trap",
        "expected_behavior": "no_without_condition",
    },

    # =========================
    # 7. 신규 — 존재하지 않는 조문 (버그 #9 확인용)
    # =========================
    {
        # DB에 없는 조문 → "없다"고 답해야 함, 임의 조문 반환 금지
        "query": "산업안전보건법 제999조 뭐야?",
        "type": "invalid",
        "expected_behavior": "not_exist",
    },
    {
        "query": "중대재해처벌법 제500조 알려줘",
        "type": "invalid",
        "expected_behavior": "not_exist",
    },

    # =========================
    # 8. 신규 — 수치/임계값 질문
    # =========================
    {
        # 숫자 기준 → 정확한 수치 포함 여부
        "query": "안전관리자 몇 명 선임해야 해?",
        "type": "reasoning",
        "expected_behavior": "condition_explanation",
    },
    {
        # 사업장 규모 → 조건부 답변
        "query": "근로자 50명이면 안전관리자 있어야 해?",
        "type": "trap",
        "expected_behavior": "conditional_answer",
    },

    # =========================
    # 9. 신규 — 경쟁 법령 질문
    # =========================
    {
        # 법령 간 우선순위 → 구체적 근거 포함 여부
        "query": "산업안전보건법이랑 건축법 중 뭐가 우선이야?",
        "type": "reasoning",
        "expected_behavior": "condition_explanation",
    },
    {
        # 의무 여부 질문 → 조건 판단 후 답변
        "query": "안전관리자 없어도 되는 사업장이 있나?",
        "type": "trap",
        "expected_behavior": "conditional_answer",
    },

    # =========================
    # 10. 신규 — 위반/처벌 질문
    # =========================
    {
        "query": "중대재해 발생하면 경영책임자 처벌은?",
        "type": "lookup",
        "expected_behavior": "conditional_answer",
    },
    {
        "query": "안전조치 안 하면 얼마나 벌금이야?",
        "type": "reasoning",
        "expected_behavior": "conditional_answer",
    },
]


# ─────────────────────────────
# SSE 스트림 수집
# ─────────────────────────────
def call_api(query: str, timeout: int = 60) -> dict:
    """SSE 스트림을 소비해 text/source 수집"""
    text_parts = []
    source = "unknown"

    try:
        with requests.post(
            API_URL,
            json={"user_id": USER_ID, "question": query},
            stream=True,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                try:
                    data = json.loads(line)
                    event = data.get("event") or data.get("type", "")
                    payload = data.get("payload", "")

                    if event == "text":
                        text_parts.append(str(payload))
                    elif event == "source":
                        # law_rag_tool → "pg" or "qdrant"
                        if isinstance(payload, dict):
                            if payload.get("law_url"):
                                source = "pg"
                            elif payload.get("retrieved_laws"):
                                source = "qdrant"
                        elif "web" in str(payload).lower():
                            source = "web"
                except (json.JSONDecodeError, TypeError):
                    continue

    except requests.exceptions.RequestException as e:
        return {"text": f"[API ERROR] {e}", "source": "error"}

    full_text = "".join(text_parts)

    # source 추론: web fallback 응답엔 "web" 키워드 미포함이므로 텍스트로 보완
    if source == "unknown":
        if any(k in full_text for k in ["OSHA", "검색 결과", "출처"]):
            source = "web"
        else:
            source = "pg"

    return {"text": full_text, "source": source}


# ─────────────────────────────
# 평가
# ─────────────────────────────
def evaluate_response(response: dict, test_case: dict) -> dict:
    checks = []
    text = response.get("text", "")

    if "must_contain" in test_case:
        ok = all(k in text for k in test_case["must_contain"])
        checks.append(("must_contain", ok, f"{test_case['must_contain']}"))

    if "expected_source" in test_case:
        ok = response.get("source") == test_case["expected_source"]
        checks.append(("expected_source", ok, f"got={response.get('source')} want={test_case['expected_source']}"))

    if "expected_article" in test_case:
        expected = test_case["expected_article"]
        if isinstance(expected, list):
            ok = any(a in text for a in expected)
            checks.append(("expected_article", ok, f"any of {expected}"))
        else:
            ok = expected in text
            checks.append(("expected_article", ok, f"{expected}"))

    if "expected_behavior" in test_case:
        behavior = test_case["expected_behavior"]
        if behavior == "not_exist":
            ok = any(k in text for k in ["없", "존재하지", "찾을 수 없"])
        elif behavior == "refuse":
            ok = any(k in text for k in ["알 수 없", "존재하지", "없는 법", "확인되지"])
        elif behavior == "conditional_answer":
            ok = any(k in text for k in ["경우", "조건", "해당하는", "판단"])
        elif behavior == "no_without_condition":
            ok = any(k in text for k in ["필요하지 않", "해당하지 않", "경우에만", "조건"])
        elif behavior == "ask_for_law_name":
            ok = any(k in text for k in ["어떤 법", "법령명", "구체적", "어느 법"])
        elif behavior == "scope_explanation":
            ok = len(text) > 80  # 최소한 설명은 했는지
        elif behavior == "condition_explanation":
            ok = any(k in text for k in ["경우", "조건", "위반", "해당"])
        else:
            ok = False
        checks.append(("behavior:" + behavior, ok, ""))

    passed = all(c[1] for c in checks)
    return {"checks": checks, "passed": passed}


# ─────────────────────────────
# 실패 유형 분류
# ─────────────────────────────
def classify_failure(test_case: dict, response: dict, checks: list) -> str:
    """실패 원인을 5개 유형 중 하나로 분류한다."""
    failed = {name for name, ok, _ in checks if not ok}

    # 소스 불일치 → fallback 오작동
    if "expected_source" in failed:
        expected = test_case.get("expected_source", "")
        got = response.get("source", "")
        if expected == "web" and got != "web":
            return "fallback_error"      # 웹으로 갔어야 하는데 못 감
        if got == "web" and expected != "web":
            return "fallback_error"      # 불필요한 웹 fallback

    # 존재하지 않는 조문을 만들어 냈음
    if "behavior:not_exist" in failed:
        return "hallucination"

    # 잘못된 조문/법령 인용
    if "expected_article" in failed:
        return "wrong_law_selection"

    # 조건부 판단이 필요한데 단순 답변
    conditional_behaviors = {"conditional_answer", "no_without_condition", "condition_explanation"}
    for name in failed:
        if name.startswith("behavior:") and name[9:] in conditional_behaviors:
            return "intent_error"

    # 필수 키워드 누락 또는 기타 출력 오류
    return "output_error"


# ─────────────────────────────
# 결과 저장
# ─────────────────────────────
FAILURES_DIR = Path(__file__).parent / "failures"
FAILURES_DIR.mkdir(exist_ok=True)


def save_failures(failed_cases: list) -> None:
    today = datetime.now().strftime("%Y%m%d")
    path = FAILURES_DIR / f"{today}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": today, "failures": failed_cases}, f, ensure_ascii=False, indent=2)
    print(f"\n💾 실패 케이스 저장: {path}")


# ─────────────────────────────
# 실행
# ─────────────────────────────
def run_all():
    total = len(TEST_CASES)
    passed_count = 0
    failed_cases = []

    # per-type tracking
    type_total: dict = defaultdict(int)
    type_passed: dict = defaultdict(int)
    failure_type_counts: dict = defaultdict(int)

    print(f"\n{'='*65}")
    print(f"  Law11 QA 테스트 — {total}개 케이스")
    print(f"{'='*65}\n")

    for i, case in enumerate(TEST_CASES, 1):
        query = case["query"]
        qtype = case["type"]
        print(f"[{i:02d}/{total}] [{qtype}] {query[:55]}...", end="", flush=True)

        t0 = time.time()
        response = call_api(query)
        elapsed = time.time() - t0

        result = evaluate_response(response, case)

        type_total[qtype] += 1
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        print(f"\r[{i:02d}/{total}] [{qtype}] {query[:50]:<52} {status} ({elapsed:.1f}s)")

        if result["passed"]:
            passed_count += 1
            type_passed[qtype] += 1
        else:
            failure_class = classify_failure(case, response, result["checks"])
            failure_type_counts[failure_class] += 1
            failed_cases.append({
                "no": i,
                "query": query,
                "type": qtype,
                "failure_class": failure_class,
                "checks": [(name, ok, detail) for name, ok, detail in result["checks"]],
                "response_preview": response["text"][:300],
                "source": response["source"],
            })

    # ── 전체 요약 ──
    print(f"\n{'='*65}")
    print(f"  전체: {passed_count}/{total} 통과  ({total - passed_count}개 실패)")
    print(f"{'='*65}")

    # ── per-type 정확도 ──
    print("\n─── 유형별 정확도 ───")
    all_types = sorted(set(type_total.keys()))
    for t in all_types:
        p = type_passed[t]
        tot = type_total[t]
        bar = "█" * p + "░" * (tot - p)
        pct = p / tot * 100 if tot else 0
        print(f"  {t:<12} {p}/{tot}  [{bar}]  {pct:.0f}%")

    # ── 실패 유형 분포 ──
    if failure_type_counts:
        print("\n─── 실패 유형 분포 ───")
        for fc, cnt in sorted(failure_type_counts.items(), key=lambda x: -x[1]):
            print(f"  {fc:<22} {cnt}건")

    # ── 실패 케이스 상세 ──
    if failed_cases:
        print("\n─── 실패 케이스 상세 ───\n")
        for f in failed_cases:
            print(f"#{f['no']} [{f['type']}] [{f['failure_class']}] {f['query']}")
            for name, ok, detail in f["checks"]:
                icon = "  ✅" if ok else "  ❌"
                print(f"  {icon} {name} {detail}")
            print(f"  source={f['source']}")
            print(f"  응답 미리보기: {f['response_preview'][:200]!r}")
            print()
        save_failures(failed_cases)

    return failed_cases


if __name__ == "__main__":
    failed = run_all()
    sys.exit(0 if not failed else 1)
