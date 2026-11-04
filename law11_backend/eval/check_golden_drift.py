"""골든셋 정답(ground_truth)이 현행 DB 조문과 어긋났는지 점검한다 (#69).

왜 필요한가:
    ground_truth는 law_chunks의 조문 전문인데, 법령은 개정된다. 정답지는
    #28 무렵 한 번 만든 뒤 갱신되지 않아 2026-11-04 점검에서 18/30이
    어긋나 있었다 — 3건은 실제 개정(제36조 2026.2.19, 제51·52조 2026.10.27),
    나머지는 옛 파서가 남긴 중복 번호(#63) 잔재였다.

    낡은 정답으로 채점하면 모델이 현행법으로 정확히 답해도 판정기가 깎는다.
    수치가 떨어지는데 원인이 품질이 아니라 정답지라, 측정 자체가 무의미해진다.
    #28에서 겪은 "골든셋 오염"과 같은 계열의 함정이다.

사용:
    python -m eval.check_golden_drift          # 보고만
    python -m eval.check_golden_drift --fix    # 현행 조문으로 갱신

어긋난 것이 있으면 exit 1 — 재측정 전 게이트로 쓸 수 있다.
"""
import argparse
import asyncio
import difflib
import json
import re
import sys
from pathlib import Path

from sqlalchemy import text

from app.config.settings import async_engine

GOLDEN = Path(__file__).parent / "golden_dataset.json"
# 0.95 미만이면 실제 개정으로 본다. 그 이상은 공백·번호 표기 차이 수준.
CONTENT_CHANGE_RATIO = 0.95

_norm = lambda t: re.sub(r"\s+", " ", (t or "")).strip()


async def _fetch(conn, law_name_norm: str, article_number_norm: str) -> str:
    row = (await conn.execute(
        text("SELECT text FROM law_chunks "
             "WHERE law_name_norm = :ln AND article_number_norm = :an LIMIT 1"),
        {"ln": law_name_norm, "an": article_number_norm},
    )).first()
    return row[0] if row else ""


async def main(fix: bool) -> int:
    doc = json.loads(GOLDEN.read_text(encoding="utf-8"))
    missing, drifted = [], []

    async with async_engine.connect() as conn:
        for case in doc["dataset"]:
            current = await _fetch(conn, case["law_name_norm"], case["article_number_norm"])
            if not current:
                missing.append(case["id"])
                continue
            if _norm(case["ground_truth"]) == _norm(current):
                continue
            ratio = difflib.SequenceMatcher(
                None, _norm(case["ground_truth"]), _norm(current)
            ).ratio()
            drifted.append((case["id"], case["article_number_norm"], ratio))
            if fix:
                case["ground_truth"] = current

    if missing:
        print(f"❌ DB에 없는 조문 {len(missing)}건: {', '.join(missing)}")
        print("   법령이 폐지됐거나 조문 번호가 바뀌었다 — 케이스 교체가 필요하다.")

    if not drifted:
        print(f"✅ 골든셋 {len(doc['dataset'])}건 모두 현행 조문과 일치")
        return 1 if missing else 0

    content = [d for d in drifted if d[2] < CONTENT_CHANGE_RATIO]
    print(f"⚠️  {len(drifted)}건 어긋남 (내용 변경 {len(content)}건 / 형식 차이 {len(drifted)-len(content)}건)\n")
    for cid, art, ratio in drifted:
        kind = "내용 변경" if ratio < CONTENT_CHANGE_RATIO else "형식만"
        print(f"  {cid:<8} 제{art:<8}조  유사도 {ratio:.2f}  {kind}")

    if fix:
        doc["updated_at"] = __import__("datetime").date.today().isoformat()
        GOLDEN.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n✅ {len(drifted)}건을 현행 조문으로 갱신했다. git diff로 확인할 것.")
        return 1 if missing else 0

    print("\n→ 갱신하려면 --fix. 재측정 전에 반드시 해소해야 한다.")
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="골든셋 정답 ↔ 현행 조문 대조")
    ap.add_argument("--fix", action="store_true", help="현행 조문으로 갱신")
    sys.exit(asyncio.run(main(ap.parse_args().fix)))
