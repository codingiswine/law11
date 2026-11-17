"""고용노동부 법령해석(법제처 DRF target=moelCgmExpc)에서 외부 테스트셋 후보를 수집한다.

골든셋 30문항은 직접 만든 질문이라, 남이 쓴 질문으로 검색 성능을 다시 측정하기 위한 원재료다.
필터: 2020-01-16(산안법 전부개정 시행) 이후 해석만 — 이전 해석은 조문 번호가 현행과 다르다.
      건설업 산업안전보건관리비 고시 질의는 DB 9개 법령 밖이라 제외.
출력: eval/external/moel_candidates.json (gold_articles는 비워 두고 사람이 라벨링)
OC 값과 OC가 박힌 상세 링크는 출력에 남기지 않는다.

    python -m eval.fetch_moel_interpretations
"""
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
OC = os.environ["LAW_OC_ID"]
SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL = "https://www.law.go.kr/DRF/lawService.do"
KEYWORDS = [
    "산업안전보건", "중대재해", "안전관리자", "보건관리자", "관리감독자", "안전보건관리책임자",
    "도급", "수급인", "산업재해", "안전보건교육", "위험성평가", "작업환경측정", "건강진단",
    "안전조치", "보건조치", "작업중지", "물질안전보건자료", "유해위험방지계획서", "공정안전보고서",
]
CUTOFF = "20200116"
OUT = Path(__file__).parent / "external" / "moel_candidates.json"


def _get(url: str, **params) -> ET.Element:
    q = urllib.parse.urlencode({"OC": OC, "target": "moelCgmExpc", "type": "XML", **params})
    with urllib.request.urlopen(f"{url}?{q}", timeout=30) as r:
        return ET.fromstring(r.read())


def search(keyword: str) -> dict[str, tuple[str, str]]:
    found, page = {}, 1
    while True:
        root = _get(SEARCH, query=keyword, display=100, page=page)
        items = root.findall("cgmExpc")
        for it in items:
            found[it.findtext("법령해석일련번호")] = (
                (it.findtext("해석일자") or "").replace(".", ""),
                it.findtext("안건명") or "",
            )
        if page * 100 >= int(root.findtext("totalCnt") or 0) or not items:
            return found
        page += 1


def keep(date: str, title: str) -> bool:
    return date >= CUTOFF and "관리비" not in title


def main() -> None:
    hits: dict[str, tuple[str, str]] = {}
    for kw in KEYWORDS:
        r = search(kw)
        print(f"{kw}: {len(r)}건")
        hits.update(r)
    cand = {k: v for k, v in hits.items() if keep(*v)}
    print(f"중복 제거 {len(hits)}건 → 필터 후 {len(cand)}건")

    rows = []
    for sid in sorted(cand, key=lambda k: cand[k][0]):
        d = _get(DETAIL, ID=sid)
        t = lambda tag: " ".join((d.findtext(tag) or "").split())  # noqa: E731
        if "관리비" in t("질의요지"):
            continue
        rows.append({
            "id": f"MOEL-{sid}", "serial": sid, "date": t("해석일자"), "title": t("안건명"),
            "case_no": t("안건번호"), "question": t("질의요지"), "answer": t("회답"),
            "reason": t("이유"), "gold_articles": [], "label_note": "",
        })
        time.sleep(0.2)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"source": "law.go.kr DRF moelCgmExpc", "cutoff": CUTOFF,
                               "keywords": KEYWORDS, "total": len(rows), "items": rows},
                              ensure_ascii=False, indent=2))
    print(f"→ {OUT} ({len(rows)}건)")


if __name__ == "__main__":
    main()
