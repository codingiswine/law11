# RAGAS baseline 이력 (골든셋 30케이스, judge `gpt-4o-mini`, ragas 0.1.21)

전문 JSON(각 ~264KB)은 `.gitignore`로 제외하고 요약만 남깁니다. 값은 소수점 둘째 자리 반올림.
`파일` 열의 `baseline_*.json`은 로컬 `eval/results/`의 원본이며, 커밋된 것은 2026-09-19 건뿐입니다.

| 측정일 (KST) | Faithfulness | Answer Relevancy | Context Precision | Context Recall | 조건 | 근거 |
|---|---|---|---|---|---|---|
| 2026-07-19 1회 | 0.86 | 0.58 | 0.96 | 0.93 | #40 **이전** (RAGAS 한국어 인코딩 버그 존재) | CHANGELOG #29 · `baseline_20260718_1522_full.json` |
| 2026-07-19 2회 | 0.79 | 0.57 | 0.99 | 0.92 | 동일 설정 재실행 | CHANGELOG #29 · `baseline_20260718_1532_full.json` |
| 2026-07-19 3회 | 0.71 | 0.57 | 0.99 | 0.92 | 동일 설정 재실행 | CHANGELOG #29 · `baseline_20260718_1547_full.json` |
| 2026-09-05 1회 | 0.69 | 0.57 | 1.00 | 0.93 | #40 **이후** (인코딩 몽키패치 적용) | CHANGELOG #40 검증 · `baseline_20260905_0034_full.json` |
| 2026-09-05 2회 | 0.74 | 0.57 | 1.00 | 0.92 | #40 이후, 같은 날 재실행 | README v1.9.4까지의 표기값 · `baseline_20260905_0913_full.json` |
| 2026-09-19 | 0.73 | 0.57 | 1.00 | 0.93 | #40 이후, 2주 후 재검증 | [`baseline_20260919_0650_full.json`](baseline_20260919_0650_full.json) (커밋됨) |

회귀 임계값(`eval/harness.py:76,81`): 기본 **5%**, Faithfulness만 **15%** — 07-19 동일 설정 3회 실행이 0.86 → 0.79 → 0.71로 ±10% 흔들린 실측 분산에서 나온 값이며, 5% 게이트로는 judge 노이즈만으로 CI가 깨졌기 때문입니다.
