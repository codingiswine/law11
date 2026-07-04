# Law11 — 프로젝트 스펙

> AI가 코드를 짤 때 지켜야 할 규칙과 절대 하면 안 되는 것.
> 이 문서를 AI에게 항상 함께 공유하세요.

---

## 기술 스택

| 영역 | 선택 | 이유 |
|------|------|------|
| Backend 프레임워크 | FastAPI (Python 3.11) | async 네이티브, SSE 스트리밍 지원, 빠른 프로토타이핑 |
| 관계형 DB | PostgreSQL 16 | 법령 조문 정확 매칭 + 대화 이력 영속 저장 |
| 벡터 DB | Qdrant | 고성능 벡터 검색, 한국어 임베딩 호환 |
| LLM | OpenAI GPT-4o | 한국어 법률 답변 품질, 기존 프롬프트 최적화 |
| Reranker (v1.1+) | BAAI/bge-reranker-v2-m3 | 오픈소스, 한국어 지원, CPU 추론 가능 |
| Frontend | React + TypeScript + Vite | 타입 안전성, 빠른 빌드 |
| 웹 검색 | DuckDuckGo (duckduckgo-search) | 무료, API 키 불필요 |
| 스케줄러 | APScheduler | 법령 주간 업데이트 자동화 |
| 배포 | Docker Compose | 백엔드 + DB 일괄 실행 |

---

## 프로젝트 구조

```
llex/
├── law11_backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── models.py        # Pydantic 요청/응답 스키마
│   │   │   └── routes.py        # POST /api/ask + tool_map
│   │   ├── config/
│   │   │   └── settings.py      # openai_client, qdrant_client, async_engine 생성
│   │   ├── core/
│   │   │   └── stream.py        # ToolChunk 정의
│   │   ├── services/
│   │   │   ├── question_router.py  # tool 분류 로직
│   │   │   ├── rag_service.py      # 검색 오케스트레이션
│   │   │   ├── qa_logger.py        # 운영 로그 기록
│   │   │   └── law_scheduler.py    # APScheduler 관리
│   │   ├── tools/
│   │   │   ├── law_rag_tool.py     # 핵심 RAG tool (SYSTEM_PROMPT 포함)
│   │   │   └── websearch_tool.py   # 웹 검색 tool
│   │   └── main.py              # FastAPI app + lifespan
│   ├── eval/                    # 평가 파이프라인
│   ├── init.sql                 # DB 스키마
│   └── requirements.txt
├── law11_frontend/
│   ├── src/
│   │   ├── components/          # ChatWindow, ChatMessage, SearchBar
│   │   ├── services/api.ts      # SSE 클라이언트
│   │   └── types/index.ts       # TypeScript 타입
│   └── index.html
├── PRD/                         # 이 문서들
└── docker-compose.yml
```

---

## 절대 하지 마 (DO NOT)

> AI에게 코드를 시킬 때 이 목록을 반드시 함께 공유하세요.

- **SYSTEM_PROMPT 임의 수정 금지** (`app/tools/law_rag_tool.py`) — 할루시네이션 방지 로직이 담겨 있음. 수정 시 eval_hallucination 재실행 필수
- **`law_name_norm`, `article_number_norm` 변경 금지** — PostgreSQL↔Qdrant 조인 키. 변경 시 검색 전체 파괴
- **`settings.*` 외부에서 클라이언트 신규 생성 금지** — `openai_client`, `qdrant_client`, `async_engine`은 `config/settings.py`에서만 생성
- **`AsyncQdrantClient` 시그니처 변경 금지** — `await qdrant.search(collection, vector, ...)` 위치 인자 고정. `query_vector=` 키워드 사용 금지
- **`meta` ToolChunk를 SSE로 유출 금지** — `meta` 타입은 `qa_logger`로만 전달, 클라이언트 응답에 포함 금지
- **Tool 추가 시 세 파일 동시 수정 필수** — `tools/<new>.py` + `routes.py의 tool_map` + `question_router.py의 valid set`
- **`start_scheduler()` / `stop_scheduler()` 는 `main.py` lifespan에서만 호출** — 중복 등록 방지
- **API 키를 코드에 직접 하드코딩 금지** — `.env` 파일 사용, `.gitignore` 확인
- **기존 `eval/logs/qa_YYYYMMDD.jsonl` 삭제 금지** — 운영 로그, perf_report.py 입력 소스
- **`eval/golden_dataset.json` 무단 수정 금지** — ground_truth 변경 시 eval 기준선이 바뀜

---

## 항상 해 (ALWAYS DO)

- **변경 전 계획 먼저 제시** — 파일 목록 + 변경 내용 요약 후 구현
- **새 기능 추가 후 eval 회귀 테스트 실행** — `python -m eval.harness --compare`
- **ToolChunk type은 규정된 5종만 사용** — `status | text | source | meta | error`
- **RAG 검색 우선순위 유지** — PG 정확 매칭 → Qdrant 벡터 → 웹 폴백 (순서 변경 금지)
- **스트리밍 청크 순서 유지** — status 먼저, text 중간, source 마지막
- **환경변수는 `.env` 파일로 관리** — Docker는 `/app/.env`, 로컬은 `law11_backend/.env`
- **Qdrant 컬렉션명은 env로만 제어** — `QDRANT_COLLECTION_NAME` 변수 사용, 코드에 `"laws"` 하드코딩 금지

---

## 로컬 실행

```bash
# Python 가상환경 활성화 (반드시 이 경로)
source /Users/daniel/Desktop/projects/law11/.venv/bin/activate

# 백엔드 단독 실행
cd law11_backend && uvicorn app.main:app --reload --port 8000

# 전체 스택 (DB 포함)
docker compose up --build
```

---

## eval 파이프라인

```bash
# 베이스라인 측정 (전체 30케이스)
cd law11_backend && python -m eval.harness

# 회귀 테스트 (직전 결과 대비 5% 이상 하락 시 exit 1)
python -m eval.harness --compare

# 빠른 확인 (5케이스 smoke)
python -m eval.harness --smoke

# 라우터 정확도
python -m eval.eval_router

# 검색 성능 (top-k 비교)
python -m eval.eval_retrieval

# 할루시네이션 검사
python -m eval.eval_hallucination
```

---

## 환경변수

| 변수명 | 설명 | 발급처 |
|--------|------|--------|
| `OPENAI_API_KEY` | GPT-4o + 임베딩 API 키 | platform.openai.com |
| `QDRANT_URL` | Qdrant 서버 주소 | 자체 호스팅 or qdrant.io |
| `QDRANT_COLLECTION_NAME` | 벡터 컬렉션명 | 기본값: `laws` |
| `DATABASE_URL` | PostgreSQL 연결 문자열 | 자체 호스팅 |
| `LAW_API_KEY` | 법령정보원 Open API 키 | law.go.kr |
| `USE_RERANKER` | Reranking 활성화 (v1.1+) | `true` / `false` |

> `.env` 파일에 저장. 절대 GitHub에 올리지 마세요.

---

## [NEEDS CLARIFICATION]

- [ ] Reranker 모델 서빙 — Docker 이미지 포함 vs 별도 모델 서버 (TorchServe 등)
- [ ] ChatSession 만료 정책 구현 방식 — APScheduler job으로 주기적 삭제 vs PostgreSQL TTL
- [ ] 법률 면책 고지 위치 — 첫 메시지 자동 표시 vs 사이드바 고정 표시
