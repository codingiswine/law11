#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_router.py
──────────────
Router 정확도 평가: keyword 방식 vs LLM 방식 비교.

법령 관련(law) vs 비법령(non-law) 이진 분류 정확도를 측정한다.
결과는 eval/results/router_accuracy.json 으로 저장된다.

실행:
    cd law11_backend
    source .venv/bin/activate
    python -m eval.eval_router
"""

import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.services.question_router import detect_tool as _detect_tool

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────
# 라벨된 테스트셋 (law = 법령 관련, non-law = 기타)
# ──────────────────────────────────────────────
LABELED_CASES: List[Dict] = [
    # ── 법령 (법령명 명시) ──
    {"question": "산업안전보건법 제17조 내용은?",                  "label": "law"},
    {"question": "산업안전보건기준에 관한 규칙 제52조 알려줘",    "label": "law"},
    {"question": "중대재해처벌법 제6조 처벌 기준은?",             "label": "law"},
    {"question": "재난 및 안전관리 기본법 제3조는?",              "label": "law"},
    {"question": "산업안전보건법 시행령 제2조 뭐야?",             "label": "law"},

    # ── 법령 (개념형, 법령명 없음) ──
    {"question": "안전관리자 선임 기준은?",                        "label": "law"},
    {"question": "비계 설치 안전 기준 알려줘",                    "label": "law"},
    {"question": "근로자 안전보건교육 의무 시간은 얼마야?",        "label": "law"},
    {"question": "위험성평가 어떻게 해야 해?",                    "label": "law"},
    {"question": "중대재해 발생하면 경영책임자 처벌은?",           "label": "law"},
    {"question": "사업주 안전조치 의무가 뭐야?",                  "label": "law"},
    {"question": "보건관리자 선임 의무 있어?",                    "label": "law"},
    {"question": "안전보건관리책임자 역할이 뭐야?",               "label": "law"},
    {"question": "공장 계단 안전 기준은?",                        "label": "law"},
    {"question": "화학물질 취급 규정은?",                         "label": "law"},

    # ── 법령 (처벌/패널티) ──
    {"question": "안전조치 위반하면 벌금 얼마야?",                "label": "law"},
    {"question": "산재 은폐하면 어떻게 되나요?",                  "label": "law"},

    # ── 비법령 (뉴스) ──
    {"question": "최근 산업재해 뉴스 알려줘",                     "label": "non-law"},
    {"question": "오늘 안전 관련 기사 있어?",                     "label": "non-law"},
    {"question": "최신 중대재해 보도 있나요?",                    "label": "non-law"},

    # ── 비법령 (블로그) ──
    {"question": "안전관리자 경험 블로그 있어?",                  "label": "non-law"},
    {"question": "산업안전 자격증 후기 알려줘",                   "label": "non-law"},

    # ── 비법령 (외국 법령) ──
    {"question": "미국 OSHA 계단 규정은?",                        "label": "non-law"},
    {"question": "일본 노동안전위생법 어떻게 돼?",                "label": "non-law"},
    {"question": "EU 산업안전 규정 알려줘",                       "label": "non-law"},

    # ── 비법령 (일상/감정) ──
    {"question": "오늘 너무 힘들어",                              "label": "non-law"},
    {"question": "고마워 잘 설명해줬어",                          "label": "non-law"},
    {"question": "안전이 중요하다고 생각해?",                     "label": "non-law"},

    # ── 경계 케이스 (애매한 질문) ──
    {"question": "오래된 건물 안전 기준 뭐야?",                   "label": "law"},
    {"question": "계단이 위험해 보여",                            "label": "law"},
    {"question": "2025년에 바뀐 법 내용은?",                      "label": "law"},
    {"question": "건설 현장 안전 어떻게 해야 해?",               "label": "law"},
]

LAW_TOOLS = {"law_rag_tool"}
NON_LAW_TOOLS = {"news_tool", "blog_tool", "websearch_tool", "general_tool", "db_query_tool_async"}


def keyword_label(tool: str) -> str:
    return "law" if tool in LAW_TOOLS else "non-law"


# ──────────────────────────────────────────────
# LLM 기반 분류
# ──────────────────────────────────────────────
ROUTER_SYSTEM = """너는 법령 챗봇의 질문 분류기다.
사용자 질문이 한국 산업안전보건 법령(산업안전보건법, 중대재해처벌법, 재난안전관리기본법 등)과
직접 관련된 질문인지 분류해.

대답은 반드시 다음 중 하나만:
  law      — 법령 조문 조회, 법적 기준, 처벌, 의무, 안전 기준 등
  non-law  — 뉴스, 블로그, 외국 법령, 감정 대화, 일상 대화, 법령과 무관

단어 하나만 출력해. 설명 금지."""


async def llm_classify(question: str) -> str:
    try:
        resp = await settings.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": question},
            ],
            temperature=0,
            max_tokens=5,
        )
        raw = resp.choices[0].message.content.strip().lower()
        return "law" if "law" in raw and "non" not in raw else "non-law"
    except Exception as e:
        print(f"  ⚠️ LLM 분류 오류: {e}")
        return "law"


# ──────────────────────────────────────────────
# 평가 실행
# ──────────────────────────────────────────────
async def evaluate():
    total = len(LABELED_CASES)
    kw_correct = 0
    llm_correct = 0
    details = []

    print(f"\n{'='*65}")
    print(f"  Router 정확도 평가 — {total}개 케이스")
    print(f"{'='*65}\n")
    print(f"  {'질문':<38} {'정답':<10} {'키워드':<10} {'LLM'}")
    print(f"  {'-'*65}")

    for case in LABELED_CASES:
        q     = case["question"]
        label = case["label"]

        # 키워드 기반
        kw_plan = await _detect_tool("eval_user", q)
        kw_pred = keyword_label(kw_plan.tool)

        # LLM 기반
        llm_pred = await llm_classify(q)

        kw_ok  = kw_pred  == label
        llm_ok = llm_pred == label
        if kw_ok:  kw_correct  += 1
        if llm_ok: llm_correct += 1

        kw_icon  = "✅" if kw_ok  else "❌"
        llm_icon = "✅" if llm_ok else "❌"

        short_q = q[:36] + ".." if len(q) > 38 else q
        print(f"  {short_q:<38} {label:<10} {kw_icon} {kw_pred:<8} {llm_icon} {llm_pred}")

        details.append({
            "question":    q,
            "label":       label,
            "kw_tool":     kw_plan.tool,
            "kw_pred":     kw_pred,
            "kw_correct":  kw_ok,
            "llm_pred":    llm_pred,
            "llm_correct": llm_ok,
        })

    kw_acc  = kw_correct  / total
    llm_acc = llm_correct / total

    print(f"\n{'='*65}")
    print(f"  키워드 기반  정확도: {kw_correct}/{total}  ({kw_acc:.1%})")
    print(f"  LLM 기반     정확도: {llm_correct}/{total}  ({llm_acc:.1%})")
    print(f"{'='*65}\n")

    # 키워드가 틀린 케이스만 출력
    kw_wrong = [d for d in details if not d["kw_correct"]]
    if kw_wrong:
        print("  ── 키워드 오분류 케이스 ──")
        for d in kw_wrong:
            print(f"    [{d['label']}→{d['kw_pred']}] {d['question']}")
        print()

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total":         total,
        "keyword_accuracy": round(kw_acc, 4),
        "llm_accuracy":     round(llm_acc, 4),
        "keyword_correct":  kw_correct,
        "llm_correct":      llm_correct,
        "details":          details,
    }

    out_path = RESULTS_DIR / "router_accuracy.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료 → {out_path}\n")
    return result


if __name__ == "__main__":
    asyncio.run(evaluate())
