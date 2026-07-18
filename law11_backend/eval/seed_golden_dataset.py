#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed_golden_dataset.py
─────────────────────────────────────────────────────────────
DB에서 지정된 법령 조문을 조회해 golden_dataset_draft.json 초안을 생성.

실행 후 golden_dataset_draft.json을 열어 ground_truth를 조문 전문에서
핵심 내용 요약으로 수정한 뒤 golden_dataset.json으로 저장.

실행:
    cd law11_backend
    source .venv/bin/activate
    python -m eval.seed_golden_dataset
"""

import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text
from app.config import settings

EVAL_DIR = Path(__file__).parent
OUTPUT_PATH = EVAL_DIR / "golden_dataset_draft.json"

# ─────────────────────────────────────────────────────────────
# 30개 테스트 케이스 정의
# (law_name_norm, article_number_norm, question, question_type)
# ─────────────────────────────────────────────────────────────
ARTICLES_TO_SEED = [
    # ── 산업안전보건법 (10개) ──────────────────────────────
    ("산업안전보건법", "17",  "산업안전보건법 제17조의 내용은 무엇인가요?",                        "direct_article"),
    ("산업안전보건법", "18",  "보건관리자를 선임해야 하는 기준은 무엇인가요?",                      "concept"),
    ("산업안전보건법", "29",  "근로자 안전보건교육의 종류와 시간 기준은 어떻게 되나요?",            "concept"),
    ("산업안전보건법", "36",  "위험성평가란 무엇이고 어떻게 실시해야 하나요?",                      "concept"),
    ("산업안전보건법", "38",  "사업주가 취해야 할 안전조치의 내용은 무엇인가요?",                    "standard"),
    ("산업안전보건법", "39",  "산업안전보건법 제39조에서 규정하는 보건조치는 무엇인가요?",           "direct_article"),
    ("산업안전보건법", "51",  "사업주가 작업을 중지할 수 있는 요건은 무엇인가요?",                   "concept"),
    ("산업안전보건법", "52",  "근로자가 작업을 중지하고 대피할 수 있는 조건은?",                     "concept"),
    ("산업안전보건법", "63",  "도급인의 안전보건조치 의무 범위는 어디까지인가요?",                    "concept"),
    # ⚠️ 2026-07-18 교정: 초기 목록의 조문 번호 13건이 질문과 무관한 조문이었음
    # (예: "감전 방지"의 정답이 제132조(양중기), "거푸집 동바리"가 제100조(띠톱기계)).
    # eval_retrieval 실패 케이스를 DB 원문과 대조해 전건 검증 후 수정 — README #25 참고.
    ("산업안전보건법", "77",  "특수형태근로종사자에 대한 안전조치 의무는 무엇인가요?",                "concept"),

    # ── 산업안전보건기준에관한규칙 (10개) ─────────────────────
    ("산업안전보건기준에관한규칙", "32",  "산업안전보건기준에 관한 규칙 제32조의 내용은?",            "direct_article"),
    ("산업안전보건기준에관한규칙", "59",  "강관비계 조립 시 준수해야 할 사항은 무엇인가요?",          "standard"),
    ("산업안전보건기준에관한규칙", "330", "거푸집 동바리 설치 기준은 어떻게 되나요?",                  "standard"),
    ("산업안전보건기준에관한규칙", "304", "전기기계·기구 사용 시 감전 방지 기준은?",                   "standard"),
    ("산업안전보건기준에관한규칙", "322", "충전전로 인근 작업 시 안전거리 기준은?",                    "standard"),
    ("산업안전보건기준에관한규칙", "230", "폭발 위험 분위기에서의 작업 기준은?",                       "standard"),
    ("산업안전보건기준에관한규칙", "338", "굴착 작업 시 지반 붕괴 방지 조치는?",                       "standard"),
    ("산업안전보건기준에관한규칙", "422", "유해물질 취급 시 필요한 안전조치는?",                       "standard"),
    ("산업안전보건기준에관한규칙", "421", "관리대상 유해물질 취급 시 적용이 제외되는 기준은?",         "concept"),
    ("산업안전보건기준에관한규칙", "500", "산업안전보건기준에 관한 규칙 제500조 내용은?",              "direct_article"),

    # ── 중대재해처벌등에관한법률 (5개) ───────────────────────
    ("중대재해처벌등에관한법률", "2",  "중대재해처벌법에서 '중대산업재해'의 정의는?",                  "concept"),
    ("중대재해처벌등에관한법률", "4",  "경영책임자의 안전보건 확보 의무 내용은 무엇인가요?",           "concept"),
    ("중대재해처벌등에관한법률", "6",  "중대산업재해 발생 시 경영책임자의 처벌 수위는?",               "penalty"),
    ("중대재해처벌등에관한법률", "10", "중대시민재해 발생 시 사업주 처벌 기준은?",                     "penalty"),
    ("중대재해처벌등에관한법률", "15", "중대재해처벌법에서 규정하는 징벌적 손해배상 기준은?",          "penalty"),

    # ── 재난및안전관리기본법 (5개) ────────────────────────────
    ("재난및안전관리기본법", "3",  "재난및안전관리기본법에서 '재난'의 정의는?",                        "concept"),
    # 구 제14조(중앙재난안전대책본부)·제34조 본조(재난관리자원 비축)는 DB 미수록이라
    # DB에 실존하는 조문 기준으로 질문 교체 (제36조 재난사태 선포, 제60조 특별재난지역)
    ("재난및안전관리기본법", "36", "재난사태 선포 요건과 절차는 무엇인가요?",                          "concept"),
    ("재난및안전관리기본법", "60", "특별재난지역 선포 기준은 무엇인가요?",                             "standard"),
    ("재난및안전관리기본법", "67", "재난관리기금 적립 기준은?",                                        "standard"),
    ("재난및안전관리기본법", "25의4", "재난예방조치 의무 내용은 무엇인가요?",                          "concept"),
]

# law_name 표시용 (조회는 norm 기준, 출력은 원본 표기)
LAW_DISPLAY_NAMES = {
    "산업안전보건법": "산업안전보건법",
    "산업안전보건기준에관한규칙": "산업안전보건기준에 관한 규칙",
    "중대재해처벌등에관한법률": "중대재해 처벌 등에 관한 법률",
    "재난및안전관리기본법": "재난 및 안전관리 기본법",
}


async def fetch_article_text(conn, law_name_norm: str, article_number_norm: str) -> Optional[str]:
    result = await conn.execute(
        text("""
            SELECT text FROM law_chunks
            WHERE law_name_norm = :law AND article_number_norm = :num
            ORDER BY id LIMIT 1
        """),
        {"law": law_name_norm, "num": article_number_norm}
    )
    row = result.fetchone()
    return row[0] if row else None


async def main():
    print("골든 데이터셋 초안 생성 시작...")
    print(f"총 {len(ARTICLES_TO_SEED)}개 조문 조회\n")

    dataset = []
    not_found = []

    async with settings.async_engine.connect() as conn:
        for idx, (law_norm, article_num, question, q_type) in enumerate(ARTICLES_TO_SEED, 1):
            article_text = await fetch_article_text(conn, law_norm, article_num)

            if article_text:
                law_display = LAW_DISPLAY_NAMES.get(law_norm, law_norm)
                dataset.append({
                    "id": f"GS-{idx:03d}",
                    "question_type": q_type,
                    "law_name": law_display,
                    "law_name_norm": law_norm,
                    "article_number": article_num,
                    "article_number_norm": article_num,
                    "question": question,
                    # ground_truth: 실제 조문 전문을 넣어둠 → 수동으로 핵심 요약으로 수정 필요
                    "ground_truth": article_text.strip(),
                    "expected_keywords": [],
                    "_note": "ground_truth를 조문 전문에서 핵심 요약으로 수정 후 golden_dataset.json으로 저장하세요."
                })
                print(f"  ✅ [{idx:02d}] {law_norm} 제{article_num}조 — {len(article_text)}자")
            else:
                not_found.append((law_norm, article_num, question))
                print(f"  ❌ [{idx:02d}] {law_norm} 제{article_num}조 — DB에 없음")

    output = {
        "version": "1.0-draft",
        "created_at": datetime.now().isoformat(),
        "description": (
            "Law11 RAG 평가용 골든 데이터셋 초안. "
            "ground_truth 필드를 조문 전문에서 핵심 요약으로 수정 후 "
            "golden_dataset.json으로 저장하세요."
        ),
        "total": len(dataset),
        "dataset": dataset,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(dataset)}/{len(ARTICLES_TO_SEED)}개 조회 성공")
    if not_found:
        print(f"\n⚠️  DB에 없는 조문 ({len(not_found)}개):")
        for law, num, q in not_found:
            print(f"    - {law} 제{num}조: {q}")
        print("  → 해당 항목은 초안에서 제외됩니다. 다른 조문 번호로 교체하세요.")
    print(f"\n초안 저장: {OUTPUT_PATH}")
    print("다음 단계: 파일을 열어 ground_truth를 수동으로 수정 후 golden_dataset.json으로 저장")


if __name__ == "__main__":
    asyncio.run(main())
