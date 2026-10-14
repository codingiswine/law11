# 평가 파이프라인 상세

루트 [README](../README.md#평가-파이프라인)에서 옮겨온 전체 문서입니다. 수치의 changelog 참조(#N)는 [CHANGELOG.md](../CHANGELOG.md) 항목 번호입니다.

RAG 시스템의 품질을 정량적으로 측정하기 위해 [RAGAS](https://docs.ragas.io/) 기반 오프라인 평가 파이프라인을 구축했습니다.

### 평가 구조

```
law11_backend/eval/
├── harness.py               # 통합 진입점: 베이스라인 + 회귀 + smoke
├── seed_golden_dataset.py   # DB 조문 → 골든셋 초안 자동 생성
├── golden_dataset.json      # 30개 테스트 케이스 (수동 검수)
├── retriever.py             # 평가용 RAG 래퍼 (non-streaming)
├── run_eval.py              # RAGAS 메트릭 계산 및 결과 저장
├── eval_router.py           # 라우터 정확도 평가
├── eval_retrieval.py        # 검색 성능 (top-k) 평가
├── eval_hallucination.py    # 할루시네이션 + Citation 검증
├── eval_multiturn.py        # 멀티턴 회귀 eval (수정한 멀티턴 버그 박제)
├── load_test.py             # 동시 접속 부하 테스트 (SSE 완료까지 측정)
├── fault_inject.py          # 의존성 장애 주입 테스트 (#31)
├── run_qa_test.py           # QA 시나리오 실행 + failures 저장
├── golden_dataset_case_law.json  # 판례 골든셋 초안 5케이스 (아직 eval 스크립트 미연결)
├── golden_dataset_draft.json     # seed_golden_dataset 출력 초안
├── _rerank_experiment.py    # 리랭커 A/B/C 비교 실험 (#25의 근거, 일회성)
├── collect_failures.py      # 실패 케이스 수집·분류
├── improvement_loop.py      # 반복 개선 루프
├── perf_report.py           # 운영 로그 기반 성능 보고서
├── logs/                    # qa_YYYYMMDD.jsonl (요청별 메타데이터)
├── failures/                # 실패 케이스 분류 결과
└── results/                 # 평가 결과 JSON (--compare 기준점)
```

### 측정 메트릭 (RAGAS 4종)

| 메트릭 | 측정 내용 | 의미 |
|---|---|---|
| **Faithfulness** | 답변이 검색된 조문에만 근거하는지 | 할루시네이션 탐지 |
| **Answer Relevancy** | 답변이 질문에 실제로 답하는지 | 응답 품질 |
| **Context Precision** | 검색된 조문 중 실제로 관련된 비율 | 검색 정밀도 |
| **Context Recall** | 정답에 필요한 조문이 검색됐는지 | 검색 재현율 |

### 베이스라인 측정 결과 (2026-07-18, 골든셋 교정 후 30케이스)

judge: `gpt-4o-mini` · ragas 0.1.21 기준 측정값입니다.

| 메트릭 | 교정 전 (07-16) | 교정 후 (07-18) |
|---|---|---|
| Faithfulness | 0.44 | **0.74** |
| Context Precision | 1.00 | 0.96 |
| Context Recall | 0.68 | **0.93** |
| Answer Relevancy | 0.00 (측정 불가) | 0.58 |

> ⚠️ 좌우 수치는 시스템 개선이 아니라 **정답지 교정**의 효과입니다 — 교정 전 골든셋은 13개 케이스의 조문 번호가 질문과 무관한 조문을 가리키고 있었고(#25), 그 상태의 낮은 수치는 시스템이 아니라 정답지의 오류를 측정한 값이었습니다.
> LLM-judge 지표는 영어 프롬프트 기반이라 한국어 답변에는 보수적으로 채점되는 경향이 있으며, 절대값보다는 파이프라인 변경 전후의 **상대 비교(회귀 감지)** 용도로 사용합니다 (`--compare` 모드, 5% 이상 하락 시 exit 1).
> 검색 단계 단독 성능(교정 후): **Top-1 66.7% · Top-3 recall 83.3%** (`eval_retrieval`, 임베딩 검색만, LLM 무관 무료 측정).

### 골든 데이터셋 구성 (30개)

| 질문 유형 | 수량 | 예시 |
|---|---|---|
| 개념형 질문 (`concept`) | 13개 | "안전관리자 선임 기준은?" |
| 기준/설치 (`standard`) | 10개 | "비계 설치 안전 기준은?" |
| 직접 조문 조회 (`direct_article`) | 4개 | "산업안전보건법 제17조 내용은?" |
| 처벌/패널티 (`penalty`) | 3개 | "중대재해 경영책임자 처벌 수위는?" |

### 평가 실행

```bash
# ⚠️ ragas 0.1.x는 앱이 고정한 langchain 0.3.x와 의존성이 충돌하므로
# 앱 환경이 아닌 백엔드 컨테이너 안에 일회성으로 설치해 실행합니다
# (컨테이너 재생성 시 초기화 → 앱 환경 오염 없음)
docker compose exec fastapi pip install -r eval/requirements-eval.txt

# 전체 평가 (30케이스) + 직전 결과와 자동 비교
docker compose exec fastapi python -m eval.harness

# 빠른 확인 (5케이스 smoke)
docker compose exec fastapi python -m eval.harness --smoke

# 회귀 테스트 (5% 이상 하락 시 exit 1)
docker compose exec fastapi python -m eval.harness --compare

# 라우터 정확도
docker compose exec fastapi python -m eval.eval_router

# 검색 성능 (top-k 비교)
docker compose exec fastapi python -m eval.eval_retrieval

# 할루시네이션 + Citation 검증
docker compose exec fastapi python -m eval.eval_hallucination
```

### 부하 테스트 (2026-07-15)

law11의 전신(작년 스타트업 인턴에서 만든 챗봇 프로젝트)은 실사용 부서의 인원 규모를 근거로 "최대 동시 사용자 10명"을 가정해 만들었고, 이 가정에 맞춰 DB 커넥션 풀을 `pool_size=10`으로 잡았습니다. 다만 이 가정 자체를 실측한 적은 없어서, `eval/load_test.py`로 검증했습니다 (SSE 스트림을 끝까지 읽어 실제 응답 완료 시간까지 측정, 직접 조문 조회·개념형·웹 폴백 질문을 섞은 10종 쿼리 사용).

| 시나리오 | 성공률 | TTFB p50 | Total p50 | Total max |
|---|---|---|---|---|
| 10명 동시 (warm) | 10/10 | 0.04s | 12.56s | 17.09s |
| 20명 동시 (warm) | 20/20 | 0.08s | 11.17s | 16.51s |

**결론**: 설계 가정(10명)의 2배인 20명 동시 요청에서도 실패 없이 처리했고, 응답 시간은 10명일 때와 거의 동일했습니다 — `pool_size=10 + max_overflow=20` 조합이 이 부하 범위에서는 병목이 아니라는 뜻입니다. 다만 웹 폴백 경로에서 Naver 검색 API 429(rate limit)를 반복 관측했습니다 — `websearch_tool.py`가 예외를 잡아 빈 결과로 처리하므로 요청 자체는 실패하지 않지만, 동시 웹 폴백이 몰리면 검색 결과 없이 답변 품질이 떨어질 수 있는 구간으로 파악했습니다.

**후속 조치**: 웹 검색 API 자체를 바꿔도(Google Custom Search는 2026년부로 신규 발급이 막혀 있어 제외, Tavily로 교체) 트래픽이 몰리면 그 공급자의 rate limit에 똑같이 걸릴 뿐이라는 점에서, 동시 호출 수 자체를 제한하는 `asyncio.Semaphore(5)`를 검색 호출부에 추가했습니다. 8개 동시 요청으로 재검증한 결과, 세마포어 도입 전에는 대기 중 타임아웃으로 3건이 빈 결과를 받았고, 타임아웃을 10초→20초로 늘린 뒤에는 8/8 전부 정상 처리됐습니다.

```bash
docker compose up -d
source .venv/bin/activate && cd law11_backend
python -m eval.load_test --users 10 --rounds 2
python -m eval.load_test --users 20 --rounds 2
```

### 단계별 소요 시간 분해 (2026-10-14, #56)

위 부하 테스트는 "20명이 실패 없이 처리된다"까지만 답할 수 있었습니다. 느린 요청이 **어느 단계에서** 느린지는
알 수 없었고(계측이 엔드포인트 경계에만 있었음), 그래서 개선 지점을 고를 근거가 없었습니다.
#56으로 구간 계측을 넣고 20명 × 3라운드(60건)를 다시 돌린 결과입니다.

| 경로 | 건수 | 검색+프롬프트 p95 | 생성 p95 | 전체 p95 |
|---|---|---|---|---|
| PostgreSQL 정확 매칭 | 13 (21%) | 10.17s | 1.73s | **11.30s** |
| Qdrant 벡터 검색 | 30 (49%) | 10.39s | 5.63s | **14.76s** |
| **웹 폴백** | 18 (30%) | **19.97s** | 0.0s ⚠️ | **20.02s** |

전체 60/60 성공, 전체 p95 18.57초.

**병목은 생성이 아니라 웹 폴백 경로였습니다.** 가장 느린 요청의 단계 타임라인:

```
[20.02s · web] 한 층에 소화기 몇 개 있어야돼?
    0.00s  ⚖️ 법령 검색 시작...
    0.00s  🧠 [Qdrant] 전체 법령 의미 검색 중...
    0.07s  ⚠️ 관련 법령 없음 → Web 검색으로 보완     ← Qdrant는 0.07초에 종료
   19.97s  ✅ Web 보완 검색 완료                     ← 웹 검색이 19.9초
```

20초는 우연이 아니라 **타임아웃 상한**(#31에서 10→20초로 연장한 값)입니다. 사실상 한계까지 대기한 것이고,
레이트리밋 방지로 넣은 `websearch_tool.py:27` `asyncio.Semaphore(5)`가 동시 20명에서 대기열을 만든 영향이
겹칩니다. 즉 **레이트리밋을 막으려 넣은 장치가 지연의 일부가 되는 트레이드오프**가 실측으로 드러났습니다.

⚠️ **측정 한계**: 웹 폴백의 `생성 0.0s`는 빠르다는 뜻이 아닙니다. 이 경로는
`law_rag_tool.py:417,574`에서 `stream=` 없이 한 번에 응답을 받으므로 첫 text 청크가 곧 마지막이고,
생성 시간이 `first_token` 구간에 흡수됩니다. 메인 경로(PG·Qdrant)만 두 구간이 실제로 분리됩니다.

재현:

```bash
python -m eval.load_test --users 20 --rounds 3
python -m eval.perf_report          # 구간별 p50/p95/max
```
