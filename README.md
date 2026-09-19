# Law11 — 산업안전보건 법령 RAG 챗봇

**한국어** | [English summary](README.en.md)

[![CI](https://github.com/codingiswine/law11/actions/workflows/ci.yml/badge.svg)](https://github.com/codingiswine/law11/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://reactjs.org/)
[![Qdrant](https://img.shields.io/badge/Qdrant-VectorDB-red.svg)](https://qdrant.tech/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.9.5-orange.svg)]()

> **이 저장소가 보여주는 것**
> 1. 측정하고 고친 기록 — changelog 56건, 전부 실측 검증 포함
> 2. 검증 체계를 직접 만든 것 — 골든셋 30문항, 회귀 하니스, 장애 주입 5종, mutation test
> 3. 표준을 실측으로 기각한 것 — Cross-Encoder Reranking 제거 (Top-1 13.3% → 66.7%)

한국 산업안전보건 법령 9개 (1,629개 조문)를 대상으로 한 **도메인 특화 RAG 시스템**입니다.  
PostgreSQL 정확 매칭 → Qdrant 의미 검색 → GPT-4o-mini 요약의 파이프라인으로 구성되며,  
멀티턴 세션, Citation 추적, SSE 기반 실시간 스트리밍을 지원하며, `/api/ask-multi` 전용 실험적 Self-RAG 할루시네이션 검증 경로도 별도로 제공합니다.

<div align="center">
  <img src="assets/law11_demo.webp" alt="Law11 Demo" width="800">
</div>

<table>
  <tr>
    <td><img src="assets/demo_shot1.png" alt="랜딩 화면" width="400"></td>
    <td><img src="assets/demo_shot2.png" alt="법령 답변 및 참고 법령 배지" width="400"></td>
  </tr>
  <tr>
    <td><img src="assets/demo_shot3.png" alt="LawSidePanel — DB 조문 원문" width="400"></td>
    <td><img src="assets/demo_shot4.png" alt="LawSidePanel — DB 미등록 법령의 법령정보원 링크" width="400"></td>
  </tr>
</table>

---

## 목차

- [프로젝트 개요](#프로젝트-개요)
- [시스템 아키텍처](#시스템-아키텍처)
- [RAG 파이프라인 상세](#rag-파이프라인-상세)
- [평가 파이프라인](#평가-파이프라인)
- [발견·수정 이력](#발견수정-이력)
- [운영 모니터링](#운영-모니터링)
- [기술 스택](#기술-스택)
- [빠른 시작](#빠른-시작)
- [데이터 현황](#데이터-현황)
- [API 레퍼런스](#api-레퍼런스)
- [개발 환경](#개발-환경)

---

## 프로젝트 개요

### 배경

작년 스타트업 인턴에서 만든 챗봇 프로젝트를 기반으로, 올해 호남권 최대 IT 교육기관 인턴십과 병행해 개인 프로젝트로 RAG 파이프라인을 전면 재설계(question_router 재작성, embedding_cache·self_rag_subgraph 신규 구현)했습니다. Self-RAG 할루시네이션 검증·Citation 추적·답변 품질 점수를 새로 추가했고, 이 과정에서 가지조문(제14조의2 등) 정규화 버그를 발견해 193개 조문을 복구했습니다. Cross-Encoder Reranking도 도입했으나 이후 실측에서 유해함이 확인돼 제거했습니다(#25). 평가 파이프라인에도 할루시네이션·Citation 검증을 확장 적용했습니다.

산업안전보건 실무자들은 9개 법령에 걸쳐 있는 수천 개 조문 중 관련 규정을 빠르게 찾아야 합니다. 기존 법제처 검색은 키워드 일치에 의존해 "안전관리자 선임 기준이 뭔가요?" 같은 자연어 질문에 답하기 어렵습니다.

Law11은 이 도메인에 특화된 RAG 시스템으로, **정확한 조문 번호를 모르는 상황**에서도 의미론적으로 가장 관련 있는 조문을 찾아 GPT가 실무 중심으로 해설합니다.

### 핵심 수치

**검증 · 품질 지표** — 전부 리포지토리의 eval 스크립트로 재현 가능한 실측값입니다 (교정된 골든셋 30케이스 기준, 2026-09-05 재측정):

| 지표 | 수치 | 조건 |
|---|---|---|
| 검색 Top-3 recall | **96.7%** | 골든셋 30케이스 ¹ |
| RAGAS Faithfulness / Answer Relevancy / Context Precision / Context Recall | **0.74 / 0.57 / 1.00 / 0.92** | 30케이스, gpt-4o-mini judge ² |
| 할루시네이션 | **명백한 날조 0/30** · GROUNDED 28/30 (93.3%) · Citation 누락 0건 | 골든셋 30케이스, DB 수록 9개 법령 범위 내 ³ |
| 라우터 정확도 | **43/43 (100%)** | 키워드 fast-path + LLM 하이브리드, 판례 케이스 11개 포함 ⁴ |
| 멀티턴 회귀 eval | 시나리오 5개 | 전부 mutation test(fix 되돌리기)로 회귀 감지력 검증 |
| 자동화 테스트 / CI | pytest 68개 | GitHub Actions — 백엔드 pytest · 프론트 typecheck/build |
| 동시 접속 부하테스트 | 20명 동시 요청 무실패 | 설계 목표 10명의 2배 |
| 장애 주입 테스트 | 결함 4건 발견·수정 | 의존성 5종(PG·Qdrant·OpenAI·Tavily·Naver) 개별 장애 주입 ⁵ |
| 문서화된 발견-수정 사이클 | changelog 49건 + 체계 도입 이전 7건 | 증상 → 근본 원인 → 실측 검증 형식, [CHANGELOG.md](CHANGELOG.md) |

¹ 복수 인정 조문 정책(#30)과 법령 용어 매핑(#33) 적용 후 값.
² RAGAS 자체의 한국어 인코딩 버그를 근본 수정(#40)한 뒤의 값. answer_relevancy는 #39에서 지표 제외했다가 복구됨.
³ 나머지 2건은 표현이 뭉개진 PARTIAL. 판정기 자체의 거짓 지적을 #46에서 수정하고, 조작 답변 4종 음성 대조군으로 탐지력 유지를 확인. **DB에 있는 9개 법령 범위 내 결과이며, 범위 밖 질문(웹 폴백 경로)까지 보증하지 않습니다.**
⁴ 판례 라우팅 케이스는 #38에서 추가.
⁵ 상세는 #31.

**시스템 개요**:

| 항목 | 수치 |
|---|---|
| 수록 법령 | 9개 (조문 1,629개) |
| 수록 판례 | 대법원 판례 52건 (6개 법령, 법령당 상한 100건) |
| 임베딩 모델 | `text-embedding-3-large` (3,072차원) |
| 평균 응답 시간 | < 3초 (스트리밍 첫 토큰 기준) |

---

## 시스템 아키텍처

<div align="center">
  <img src="assets/architecture.svg" alt="Law11 전체 아키텍처" width="900">
</div>

```
사용자 질문
    │
    ▼
┌─────────────────────────────────────────────┐
│  Question Router (LLM Hybrid)               │
│  DB 세션 컨텍스트 연동 · 외국 법령 자동 전환   │
│  키워드 fast-path → 애매한 질문은 LLM 분류    │
└─────────────┬───────────────────────────────┘
              │ ToolPlan (tool + args + context)
              ▼
┌─────────────────────────────────────────────────────────────┐
│  Tool 선택 (tool_map)                                        │
│                                                             │
│  law_rag_tool     — 국내 법령 RAG (기본 경로)                │
│  case_law_rag_tool — 대법원 판례 검색 (#38)                  │
│  news_tool        — 산업안전 관련 뉴스 검색                   │
│  blog_tool        — 블로그 콘텐츠 검색                       │
│  websearch_tool   — 외국 법령 / 일반 웹 검색                  │
│  db_query_tool    — DB 직접 조회 (통계/이력)                  │
│  general_tool     — 일반 대화 / 법령 외 질문                  │
└─────────────┬───────────────────────────────────────────────┘
              │ (law_rag_tool 경로)
              ▼
┌─────────────────────────────────────────────┐
│  Law RAG Tool (law_rag_tool.py)             │
│                                             │
│  ① PostgreSQL 정확 매칭                     │
│     WHERE law_name_norm = ?                 │
│           AND article_number_norm = ?       │
│     ↓ (miss)                                │
│  ② Qdrant 의미 검색 (limit=10)              │
│     → 코사인 유사도 상위 5개                │
│     threshold=0.45/0.5                      │
│     ↓ (miss)                                │
│  ③ Web Search Fallback                     │
│                                             │
└─────────────┬───────────────────────────────┘
              │ 조문 텍스트 + citations
              ▼
┌─────────────────────────────────────────────┐
│  GPT-4o-mini 스트리밍 요약                   │
│  temperature=0.2, stream=True               │
└─────────────┬───────────────────────────────┘
              │ SSE (text/event-stream)
              │
              ├──→ QA Logger (JSONL)          ← retrieval 메타데이터
              ├──→ Citations 테이블 저장       ← 인용 조문 + 신뢰도 점수
              └──→ React 프론트엔드 (3패널 레이아웃)
                   ├── 좌측 사이드바 (대화 히스토리)
                   ├── 법령 칩 (score 배지, 웹 fallback 인용 포함)
                   └── 우측 LawSidePanel (조문 원문 / 법령정보원 링크)
```

> ⚠️ **실험적 기능 — 별도 엔드포인트**: 아래 Self-RAG 검증은 `/api/ask-multi`(LangGraph 멀티 에이전트) 전용 경로에서만 동작하며, 위 메인 `/api/ask` 파이프라인(law_rag_tool.py → GPT-4o-mini)에는 적용되지 않습니다.

```
┌─────────────────────────────────────────────┐
│  Self-RAG 검증 (self_rag_subgraph.py)        │
│  /api/ask-multi 전용                        │
│  ① 할루시네이션 판정 (grade_hallucination)   │
│  ② 관련성 판정 (grade_relevance)            │
│  ③ 재시도 최대 2회 → websearch fallback      │
└───────────────────────────────────────────────┘
```

### 서비스 구성 (Docker Compose)

| 서비스 | 이미지 | 포트 | 역할 |
|---|---|---|---|
| `fastapi` | custom build | 8000 | FastAPI 백엔드 |
| `frontend` | Nginx Alpine | 3000 | React 정적 서빙 |
| `postgres` | postgres:15-alpine | 5432 | 조문 원문 + 대화 이력 + Citations |
| `qdrant` | qdrant/qdrant | 6333 | 벡터 유사도 검색 |

### 주요 파일 구조

| 파일 | 역할 |
|---|---|
| `core/plan.py` — `ToolPlan` | 라우터 출력: `tool` 이름 + `args` 딕셔너리 |
| `core/stream.py` — `ToolChunk` | 스트리밍 단위: `type` ∈ `{status,text,source,meta,error}` |
| `app/services/question_router.py` | LLM Hybrid 툴 선택 (키워드 fast-path + LLM fallback + DB 세션 컨텍스트) |
| `app/services/embedding_cache.py` | SQLite 기반 임베딩 캐시 (SHA-256 키) |
| `app/services/rag_grader.py` | 할루시네이션/관련성 판정 함수 (`/api/ask-multi` 전용, 실험적) |
| `app/services/self_rag_subgraph.py` | LangGraph Self-RAG 서브그래프 (4노드 + 2 conditional edge) — `/api/ask-multi` 전용, 실험적 |
| `app/services/langgraph_multi_agent.py` | LangGraph StateGraph 멀티 에이전트 (`/api/ask-multi` 전용, 실험적). 팩토리 함수(`_make_tool_node`)로 5개 tool 노드 생성, 그래프는 모듈 로드 시 1회 컴파일 후 싱글턴 재사용 |
| `app/services/rag_service.py` | eval용 Qdrant 검색 래퍼 + `get_embedding_async` re-export |
| `app/services/law_scheduler.py` | APScheduler — 주간 법령·판례 업데이트 + 일일 chat_history 백업 (job 3개) |
| `app/services/backup_service.py` | `chat_history` JSON 덤프 (최근 30개 보관, #44) |
| `app/services/qa_logger.py` | Retrieval 메타데이터 JSONL 로깅 |
| `app/services/metrics_service.py` | Prometheus 메트릭 수집 |
| `app/api/routes.py` | SSE 엔드포인트, 세션 관리, Citation 저장, 품질 점수 |
| `app/config/settings.py` | 환경변수 로딩(python-dotenv) + 비동기 클라이언트 싱글턴 (OpenAI / Qdrant / SQLAlchemy) |
| `app/tools/law_rag_tool.py` | 3단 검색 + Citation 이벤트 + 웹 fallback 인용 추출 |
| `app/tools/law_updater_async.py` | 법제처 DRF API → PG + Qdrant 동기화 (비동기) |
| `app/tools/case_law_rag_tool.py` | 대법원 판례 RAG — `case_law_chunks` + Qdrant `case_laws` 컬렉션 (#38) |
| `app/tools/case_law_updater_async.py` | 법제처 DRF `target=prec` → 판례 수집·동기화 (#38) |

---

## RAG 파이프라인 상세

### 검색 계층 설계

단순 벡터 검색만으로는 "산업안전보건법 제17조"처럼 정확한 조문을 지정한 질문에서 노이즈가 생깁니다. 반대로 PostgreSQL 정확 매칭만 쓰면 "안전관리자 선임 기준은?" 같은 개념형 질문에서 조문 번호를 알 수 없어 검색이 실패합니다. 두 방식을 계층화해 각 쿼리 유형에 최적의 경로를 사용합니다.

```
질문 유형          경로                                  특징
────────────────────────────────────────────────────────────────
직접 조문 조회   PostgreSQL 정확 매칭 (1ms)              법령명 + 조문번호 인덱스
개념형 질문      Qdrant top-10 → 코사인 상위 5           코사인 유사도 순
외국/국제 법령   Web Search 즉시 분기                    OSHA, ISO 등 키워드 감지
법령 외 질문     Web Search Fallback                     일반 웹 검색
```

### Reranking을 쓰지 않는 이유

초기에는 Qdrant 후보 10개를 `cross-encoder/ms-marco-MiniLM-L-6-v2`로 재순위했지만, 교정된 골든셋 30케이스 실측(`eval/_rerank_experiment.py`)에서 이 영어 전용 모델이 한국어 조문을 사실상 무작위 재배열해 **Top-1 정확도를 66.7% → 13.3%로 파괴**하는 것이 확인돼 제거했습니다. 다국어 CE(`mmarco-mMiniLMv2`)도 순수 벡터 순서를 이기지 못했습니다 (`text-embedding-3-large`가 이미 충분히 강력). 상세는 changelog #25 참고.

### 임베딩 캐시

동일한 질문의 반복 임베딩 생성을 방지하기 위해 SQLite 기반 로컬 캐시를 구현했습니다 (`embedding_cache.py`). 캐시 히트 시 OpenAI API 호출 없이 즉시 반환합니다.

```python
# 캐시 키: SHA-256(query text)
# 저장: .cache/embedding_cache.db (SQLite)
```

### Self-RAG 할루시네이션 검증

> ⚠️ **실험적 기능** — `/api/ask-multi`(LangGraph 멀티 에이전트) 전용이며, 메인 `/api/ask` 경로(law_rag_tool.py)에는 적용되지 않습니다.

`/api/ask-multi` 경로의 답변은 `self_rag_subgraph.py`의 LangGraph 서브그래프를 거쳐 품질을 검증합니다.

```
retrieve() → grade_hallucination() → grade_relevance()
                  ↓ HALLUCINATION           ↓ NOT_RELEVANT
              재시도 (최대 2회)          websearch_fallback()
```

- **GROUNDED**: 답변의 모든 주장이 조문에서 확인 가능 → 그대로 반환
- **PARTIAL/HALLUCINATION**: 재시도 또는 웹 검색 fallback
- **NOT_RELEVANT**: 검색 결과가 질문과 무관 → 웹 검색 fallback

### 멀티턴 세션

프론트엔드가 `session_id`(UUID)를 생성해 매 요청에 포함합니다. 백엔드는 `chat_history` 테이블에서 최근 5개 교환 쌍을 읽어 LLM 프롬프트 앞에 삽입합니다.

```python
# app/services/question_router.py
async def _load_session_context(session_id: str, limit: int = 5) -> str:
    """DB에서 최근 N 교환 쌍을 '사용자: ...\nLaw11: ...' 형식으로 반환"""
```

### Citation 추적

법령 RAG 경로에서 GPT에 전달한 조문의 메타데이터(law_name, article_number, score, rank)를 `citations` 테이블에 저장하고 SSE `source` 이벤트로 클라이언트에 전송합니다. 프론트엔드는 신뢰도 점수 배지가 있는 법령 칩으로 표시합니다.

### 답변 품질 점수

응답이 DB에 저장될 때 자동으로 품질 점수를 산출합니다. 법령명 참조(`「...」`)와 조문 번호(`제N조`) 출현 횟수를 기반으로 0–100점을 계산하며, `chat_history.score` 컬럼에 저장됩니다.

---

## 평가 파이프라인

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

---

## 발견·수정 이력

증상 → 근본 원인 → 실측 검증 형식으로 56건을 기록했습니다.
전체 목록: [CHANGELOG.md](CHANGELOG.md)

대표 사례:
- 골든 데이터셋 13건 오염 발견 — 교정하자 Top-3 recall 46.7% → 83.3%로 정상화 (#25)
- 가지조문(제N조의M) 정규화 붕괴로 소실돼 있던 조문 193개 복구 (#28)
- 표준처럼 쓰던 Cross-Encoder Reranking이 유해함을 실측 후 제거 (#25)

---

## 운영 모니터링

### 자동 업데이트 · 백업 스케줄러

`law_scheduler.py`가 FastAPI lifespan에 등록되어 다음 job 3개를 실행합니다 (KST).

| job id | 주기 | 작업 |
|---|---|---|
| `weekly_law_update` | 매주 월 03:00 | 법제처 DRF API → PostgreSQL + Qdrant `laws` 동기화 |
| `weekly_case_law_update` | 매주 월 04:00 | 대법원 판례 → `case_law_chunks` + Qdrant `case_laws` 동기화 |
| `daily_chat_backup` | 매일 05:00 | `chat_history` JSON 백업 (`backups/`, 최근 30개 보관) |

```bash
# 수동 즉시 업데이트
docker compose exec fastapi python -m app.tools.law_updater_async --all
docker compose exec fastapi python -m app.tools.case_law_updater_async --all

# HTTP로 트리거 (X-Admin-Key 필요 — API 레퍼런스 참고)
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" http://localhost:8000/api/admin/update-laws
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" http://localhost:8000/api/admin/backup-chat-history
```

### QA 로그

요청마다 retrieval 메타데이터가 `eval/logs/qa_YYYYMMDD.jsonl`에 자동 기록됩니다.

```json
{
  "ts": "2026-06-21T12:00:00",
  "tool": "law_rag_tool",
  "query": "안전관리자 선임 기준은?",
  "query_type": "semantic",
  "selected_source": "qdrant",
  "selected_articles": ["산업안전보건법 제17조"],
  "fallback_used": false,
  "confidence_score": 0.5712
}
```

### Prometheus 메트릭

| 메트릭 | 설명 |
|---|---|
| `law11_requests_total` | 엔드포인트·agent별 요청 수 |
| `law11_response_time_seconds` | 응답 시간 히스토그램 |
| `law11_tokens_used_total` | 모델별 토큰 사용량 |
| `law11_errors_total` | 에러 유형별 카운터 |
| `law11_agent_usage_total` | agent(tool)별 사용 횟수 |
| `law11_active_requests` | 처리 중인 요청 수 (Gauge) |

```bash
curl http://localhost:8000/api/metrics          # Prometheus 원시 메트릭
curl http://localhost:8000/api/metrics/summary  # 요약
```

---

## 기술 스택

### Backend

| 기술 | 버전 | 용도 |
|---|---|---|
| FastAPI | 0.115 | 비동기 API 서버, SSE 스트리밍 |
| SQLAlchemy | 2.0 | 비동기 PostgreSQL ORM |
| asyncpg | 0.30 | PostgreSQL 비동기 드라이버 |
| Qdrant Client | 1.11 | 벡터 유사도 검색 |
| LangGraph | 0.2 | Self-RAG 서브그래프 + 멀티 에이전트 |
| LangChain | 0.3 | LLM 체인 유틸 |
| APScheduler | 3.x | 법령 자동 업데이트 스케줄러 |
| RAGAS | 0.1 | RAG 평가 파이프라인 |
| Prometheus Client | - | 운영 메트릭 수집 |

### Frontend

| 기술 | 버전 | 용도 |
|---|---|---|
| React | 19 | UI 컴포넌트 (3패널 레이아웃) |
| TypeScript | 5.9 | 타입 안전성 |
| Vite | 7.1 | 빌드 도구 |
| TailwindCSS | 4.1 | 스타일링 |

**UI 구조:** 좌측 다크 사이드바(대화 히스토리) + 중앙 채팅 + 우측 법령 패널(클릭 시 조문 원문 표시, DB 미등록 법령은 법령정보원 링크)

### Infrastructure

```
Docker Compose  │  Nginx Alpine (프론트엔드 서빙)
PostgreSQL 15   │  Qdrant (벡터 DB)
SQLite          │  임베딩 캐시 (.cache/embedding_cache.db)
```

---

## 빠른 시작

### 사전 요구사항

- Docker 20.10+, Docker Compose 2.0+
- OpenAI API 키

### 실행

```bash
git clone https://github.com/codingiswine/law11.git
cd law11

# 환경 변수 설정
cp law11_backend/.env.example law11_backend/.env
# law11_backend/.env 편집: OPENAI_API_KEY, DB_PASS 입력

# 빌드 및 실행
docker compose up --build

# 법령 데이터 로드 (최초 1회, 별도 터미널)
docker compose exec fastapi python -m app.tools.law_updater_async --all
```

| 서비스 | URL |
|---|---|
| 프론트엔드 | http://localhost:3000 |
| API 문서 (Swagger) | http://localhost:8000/docs |
| 헬스 체크 | http://localhost:8000/health |

### 환경 변수

| 변수 | 필수 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API 키 |
| `DB_PASS` | ✅ | PostgreSQL 비밀번호 |
| `LAW_OC_ID` | ✅ | 법제처 DRF API OC ID |
| `ADMIN_API_KEY` | - | `/api/admin/*` 인증 키 (`X-Admin-Key` 헤더). 미설정 시 관리자 엔드포인트는 503으로 비활성화 (#47) |
| `LLM_MODEL` | - | 생성·라우팅·판정 모델 (기본: `gpt-4o-mini`, #48) |
| `EMBEDDING_MODEL` | - | 임베딩 모델 (기본: `text-embedding-3-large`, #48) |
| `QDRANT_COLLECTION_NAME` | - | 법령 Qdrant 컬렉션명 (기본: `laws`) |
| `QDRANT_CASE_LAW_COLLECTION_NAME` | - | 판례 Qdrant 컬렉션명 (기본: `case_laws`, #38) |
| `CORS_ORIGINS` | - | 허용 오리진 콤마 구분 (기본: localhost 목록, #36) |
| `OPENAI_PROJECT_ID` | - | OpenAI 프로젝트 ID (선택) |
| `TAVILY_API_KEY` | - | 웹 폴백 검색 (일반 웹) |
| `NAVER_CLIENT_ID` | - | Naver 뉴스/블로그 검색 (news_tool/blog_tool 전용) |
| `NAVER_CLIENT_SECRET` | - | Naver 뉴스/블로그 검색 (news_tool/blog_tool 전용) |

---

## 데이터 현황

### 수록 법령

| 법령명 | 조문 수 |
|---|---|
| 산업안전보건기준에 관한 규칙 | 672 |
| 산업안전보건법 시행규칙 | 246 |
| 산업안전보건법 | 185 |
| 산업안전보건법 시행령 | 124 |
| 재난 및 안전관리 기본법 시행령 | 185 |
| 재난 및 안전관리 기본법 | 147 |
| 재난 및 안전관리 기본법 시행규칙 | 41 |
| 중대재해 처벌 등에 관한 법률 | 16 |
| 중대재해 처벌 등에 관한 법률 시행령 | 13 |
| **합계** | **1,629** (가지조문 소실 복구 후, #28) |

### 법령 자동 업데이트

법제처 DRF(Data Release Format) API를 통해 법령 개정 시 자동으로 PostgreSQL과 Qdrant를 동기화합니다. `law_scheduler.py`가 FastAPI lifespan에 등록되어 **매주 월요일 새벽 3시**에 자동 실행됩니다.

---

## API 레퍼런스

### `POST /api/ask` — 법령 질의 (SSE 스트리밍)

```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "산업안전보건법 제17조 내용은?", "session_id": "uuid-here"}'
```

**SSE 응답 형식**:

```
data: {"event": "status", "payload": "⚖️ 법령 검색 시작..."}
data: {"event": "status", "payload": "✅ [Qdrant] 유사도 0.57 조문 발견"}
data: {"event": "text",   "payload": "산업안전보건법 제17조는..."}
data: {"event": "source", "payload": {"retrieved_laws": [{"law_name": "산업안전보건법", "article_number": "17", "score": 0.5712, "rank": 1}], "law_url": "https://..."}}
data: {"event": "saved",  "payload": "42"}
data: {"event": "status", "payload": "✅ 대화 저장 완료"}
```

| event 타입 | 내용 |
|---|---|
| `status` | 처리 단계 메시지 |
| `text` | 실제 답변 텍스트 (스트리밍) |
| `source` | 인용 조문 목록 (law_name, article_number, score, rank) |
| `saved` | 저장된 DB 레코드 ID |
| `error` | 오류 메시지 (DB 저장 실패 등 비치명적 경고 포함 — changelog #12·#17에서 미지원이던 `warning`을 `error`로 통일) |

### `GET /api/session/{session_id}` — 세션 대화 이력 조회

```bash
curl http://localhost:8000/api/session/my-session-uuid
```

### `DELETE /api/session/{session_id}` — 세션 삭제

```bash
curl -X DELETE http://localhost:8000/api/session/my-session-uuid
```

### `GET /api/law` — 특정 조문 직접 조회

```bash
curl "http://localhost:8000/api/law?name=산업안전보건법&article=17"
```

### `GET /api/history` — 전체 대화 이력 조회

```bash
curl "http://localhost:8000/api/history?limit=50&user_id=law11_user"
```

### `POST /api/feedback` — 사용자 피드백

```bash
curl -X POST http://localhost:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{"message_id": 42, "value": 1}'
# value: 1 = 👍, -1 = 👎
```

### `GET /api/metrics` — Prometheus 메트릭

```bash
curl http://localhost:8000/api/metrics
curl http://localhost:8000/api/metrics/summary
```

### `GET /api/history/stats` — 대화 통계

```bash
curl http://localhost:8000/api/history/stats
```

### `GET /api/dashboard` — 운영 모니터링 대시보드 (HTML)

브라우저에서 <http://localhost:8000/api/dashboard> 접속. 자세한 내용은 [운영 모니터링](#운영-모니터링) 참고.

### `POST /api/ask-multi` — LangGraph 멀티 에이전트 + Self-RAG (실험적, SSE)

요청·응답 형식은 `/api/ask`와 동일하며, 답변이 `self_rag_subgraph.py` 검증을 거칩니다.

```bash
curl -X POST http://localhost:8000/api/ask-multi \
  -H "Content-Type: application/json" \
  -d '{"question": "안전관리자 선임 기준은?", "session_id": "uuid-here"}'
```

### `POST /api/admin/update-laws` · `POST /api/admin/backup-chat-history` — 관리자 (인증 필요)

`X-Admin-Key` 헤더가 `ADMIN_API_KEY`와 일치해야 합니다. 키 미설정 시 503, 불일치 시 401 (#47).

```bash
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" http://localhost:8000/api/admin/update-laws
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" http://localhost:8000/api/admin/backup-chat-history
```

---

## 개발 환경

### 백엔드 로컬 실행

```bash
# venv는 프로젝트 루트에 있음
source .venv/bin/activate
cd law11_backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 프론트엔드 로컬 실행

```bash
cd law11_frontend
npm install
npm run dev   # http://localhost:5173
```

### 테스트 실행

```bash
source .venv/bin/activate
cd law11_backend && python -m pytest tests/ -v
```

### 유용한 Docker 명령어

```bash
# 백엔드 로그 실시간 확인
docker compose logs -f fastapi

# 백엔드만 재빌드
docker compose up -d --no-deps --build fastapi

# PostgreSQL 직접 접속
docker compose exec postgres psql -U daniel -d law11

# 법령 데이터 업데이트
docker compose exec fastapi python -m app.tools.law_updater_async --all
```

---

## ☁️ 클라우드 배포 경험 (AWS EC2)

로컬 Docker Compose 환경을 AWS EC2(t3.micro, Amazon Linux 2023)에 실제로
배포해본 경험입니다. 단순히 서버를 켜는 것을 넘어, 배포 과정에서 마주친
두 가지 실제 문제를 직접 진단하고 해결했습니다.

### 배포 전 보안 점검

Claude Code로 배포 전 체크리스트를 점검하여, PostgreSQL(5432)과
Qdrant(6333/6334)가 기본 설정상 `0.0.0.0`에 바인딩되어 외부에 노출될
수 있는 문제를 발견했습니다. FastAPI/React는 실제 사용자 접속이
필요하므로 `0.0.0.0`으로 유지하되, DB/Qdrant는 컨테이너 내부 통신만
필요하므로 `127.0.0.1`로 바인딩을 제한하여, AWS 보안그룹 설정을
깜빡하더라도 DB가 원천적으로 외부에 노출되지 않도록 조치했습니다.

### 트러블슈팅 1 — Docker Buildx 누락

`docker compose up -d` 실행 시 `compose build requires buildx 0.17.0
or later` 에러 발생. Docker 엔진은 설치됐지만 이미지 빌드에 필요한
buildx 플러그인이 없었던 것이 원인이었습니다. GitHub Releases API로
최신 버전을 동적으로 조회해 `~/.docker/cli-plugins/`에 직접 설치하여
해결했습니다. (첫 시도에서는 하드코딩한 버전 태그가 존재하지 않아
9바이트짜리 에러 페이지만 다운로드되는 문제를 겪었고, 파일 크기로
다운로드 실패를 판별한 뒤 동적 버전 조회 방식으로 재해결했습니다.)

### 트러블슈팅 2 — crypto.randomUUID Secure Context 에러

배포 후 프론트엔드 접속 시 흰 화면과 함께
`crypto.randomUUID is not a function` 에러 발생. 브라우저 Console
로그를 통해 원인을 특정했습니다 — `crypto.randomUUID`는 브라우저
보안 정책상 HTTPS 또는 localhost에서만 동작하며, IP 주소를 통한
평문 HTTP 접속은 "안전하지 않은 컨텍스트"로 간주되어 API 자체가
차단됩니다. 도메인·인증서 없이도 빠르게 검증하기 위해 SSH 로컬
포트 포워딩(`ssh -L 3000:localhost:3000`)으로 원격 포트를
localhost로 위장시켜 문제를 우회했습니다.

### 배포 스택

- **인프라**: AWS EC2 (t3.micro, Amazon Linux 2023), 보안그룹으로
  인바운드 포트 제한
- **접근 제어**: IAM 사용자 분리, MFA, Budget 알림으로 계정 보안 확보
- **비밀 정보 관리**: `.env` 파일은 git에 포함하지 않고 `scp`로 직접
  전송, Claude Code로 git 히스토리 내 유출 여부 사전 검증

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 벡터 검색 결과 없음 | Qdrant 데이터 미적재 | `law_updater_async --all` 실행 |
| `DB_PASS` 오류로 시작 실패 | `.env` 파일 누락 | `.env.example` 복사 후 값 입력 |
| SSE 응답 끊김 | Nginx 프록시 버퍼링 | `proxy_buffering off` 설정 확인 |
| 임베딩 캐시 오류 | `.cache/` 권한 문제 | `chmod 777 .cache/` |
| uvicorn 명령어 없음 | pyenv venv 충돌 | `python -m uvicorn` 사용 |

---

## 라이선스

MIT License © 2024 Daniel Shin

---

<div align="center">
  <p>Developer: Daniel Shin · <a href="mailto:codingiswine@gmail.com">codingiswine@gmail.com</a> · <a href="https://github.com/codingiswine">@codingiswine</a> (GitHub)</p>
</div>
