# Law11 FastAPI Backend

비동기 FastAPI + OpenAI + PostgreSQL + Qdrant 기반의 한국 산업안전보건 법령 RAG 챗봇 백엔드입니다.
Router → ToolPlan → ToolChunk 스트리밍 파이프라인으로 구성되어, 법령/판례/뉴스/블로그/웹/DB 조회를 질문에 맞게 골라 실시간 SSE로 응답합니다.

전체 시스템 설명·평가 결과·changelog는 [저장소 루트 README](../README.md)를 참고하세요. 이 문서는 백엔드 실행·구조·API에만 집중합니다.

---

## 🚀 Quick start

```bash
cd law11_backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env             # 환경 변수 템플릿 복사
# .env 를 편집해 OpenAI / PostgreSQL / Qdrant 정보를 입력

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

저장소 루트에서 `docker compose up -d` 로 PostgreSQL·Qdrant·백엔드·프론트를 한 번에 띄울 수도 있습니다 (`../DEPLOYMENT.md` 참고).

- API 문서: http://localhost:8000/docs
- 헬스체크: http://localhost:8000/health

---

## 🧱 Architecture

```
law11_backend/
├── app/
│   ├── main.py                      # FastAPI 엔트리포인트, CORS, lifespan 스케줄러, /admin 라우트
│   ├── config/settings.py           # 환경변수 로딩 + Async 클라이언트 싱글턴 (OpenAI/Qdrant/SQLAlchemy)
│   ├── api/
│   │   ├── models.py                # QueryRequest / FeedbackRequest (Pydantic)
│   │   └── routes.py                # SSE 엔드포인트, 세션 관리, Citation 저장, 품질 점수
│   ├── services/
│   │   ├── question_router.py       # 키워드 fast-path + LLM 하이브리드 툴 선택
│   │   ├── rag_service.py           # eval용 Qdrant 검색 래퍼 + get_embedding_async
│   │   ├── embedding_cache.py       # SQLite 기반 임베딩 캐시 (SHA-256 키)
│   │   ├── rag_grader.py            # 할루시네이션/관련성 판정 (/api/ask-multi 전용, 실험적)
│   │   ├── self_rag_subgraph.py     # LangGraph Self-RAG 서브그래프 (/api/ask-multi 전용, 실험적)
│   │   ├── langgraph_multi_agent.py # LangGraph StateGraph 멀티 에이전트 (/api/ask-multi 전용, 실험적)
│   │   ├── law_scheduler.py         # APScheduler 주간 법령 자동 업데이트
│   │   ├── backup_service.py        # chat_history 일일 백업
│   │   ├── metrics_service.py       # Prometheus 메트릭 수집
│   │   └── qa_logger.py             # Retrieval 메타데이터 JSONL 로깅
│   └── tools/                       # law / case_law / news / blog / websearch / db / general
├── core/                            # 공통 유틸 (앱 패키지 밖 최상위)
│   ├── logger.py
│   ├── plan.py                      # ToolPlan dataclass
│   └── stream.py                    # ToolChunk dataclass
├── eval/                            # 평가 하네스 (골든셋, RAGAS, 라우터/검색/할루시네이션 eval, 부하·장애주입)
├── tests/                           # pytest (mock 기반, 실제 API/DB 호출 없음)
├── Dockerfile
├── init.sql
└── requirements.txt
```

핵심 흐름
- `question_router.detect_tool` → `ToolPlan` 생성
- `routes.run_tool` → `tool_map`에서 Tool 실행, `ToolChunk` 스트리밍
- 응답 완료 시 chat_history + citations 저장 (Async PostgreSQL, 품질 점수 포함)

---

## 🔐 Environment variables

전체 목록과 설명은 `.env.example` 에 있습니다. 필수 항목만 추리면:

```env
OPENAI_API_KEY=sk-...
DB_NAME=law11
DB_USER=daniel
DB_PASS=your_secure_password_here
DB_HOST=postgres            # Docker: postgres, Local: localhost
DB_PORT=5432
QDRANT_HOST=qdrant          # Docker: qdrant, Local: localhost
QDRANT_PORT=6333
LAW_OC_ID=your_law_go_drf_key
```

선택 항목: `LLM_MODEL`(기본 `gpt-4o-mini`), `EMBEDDING_MODEL`(기본 `text-embedding-3-large`),
`TAVILY_API_KEY`, `NAVER_CLIENT_ID/SECRET`, `ADMIN_API_KEY`, `CORS_ORIGINS`.

`ADMIN_API_KEY`를 설정하지 않으면 `/api/admin/*` 는 503으로 **비활성화**됩니다 (fail-closed).

---

## 📡 API surface

| Method | Path | Description |
| ------ | ---- | ----------- |
| POST | `/api/ask` | 기본 RAG 경로 — SSE 스트리밍 응답 |
| POST | `/api/ask-multi` | LangGraph Self-RAG 할루시네이션 검증 경로 (실험적) |
| GET | `/api/history` | 대화 이력 조회 (`user_id`, `limit`) |
| GET | `/api/history/stats` | 대화 통계 |
| GET | `/api/session/{session_id}` | 세션 대화 이력 (`limit`) |
| DELETE | `/api/session/{session_id}` | 세션 삭제 (204) |
| GET | `/api/law` | 조문 직접 조회 (`name`, `article`) |
| POST | `/api/feedback` | 👍/👎 피드백 (`message_id`, `value`) |
| GET | `/api/metrics` | Prometheus 포맷 메트릭 |
| GET | `/api/metrics/summary` | 메트릭 요약 (JSON) |
| GET | `/api/dashboard` | 운영 모니터링 HTML 대시보드 |
| GET | `/api/health`, `/health` | 서버 상태 |
| POST | `/api/admin/update-laws` | 법령 즉시 최신화 (X-Admin-Key 필요) |
| POST | `/api/admin/backup-chat-history` | chat_history 즉시 백업 (X-Admin-Key 필요) |

`POST /api/ask` 요청 본문 (`question` 은 최대 1000자, 초과 시 422):
```json
{
  "question": "소화기 점검 주기는 어떻게 되나요?",
  "search_mode": "general",
  "session_id": "uuid-or-null"
}
```

응답은 `text/event-stream` 이며 각 라인은 JSON 직렬화된 `ToolChunk` 입니다
(`type` 필드는 직렬화 시 `event` 키로 나갑니다):
```json
{"event":"status","payload":"⚖️ 법령 검색 시작...","at":1757000000.0}
{"event":"text","payload":"산업안전보건법 제17조는...","at":1757000000.1}
{"event":"source","payload":{"retrieved_laws":[{"law_name":"산업안전보건법","article_number":"17","score":0.5712,"rank":1}]},"at":1757000000.2}
```

`event` 타입: `status` · `text` · `source` · `meta` · `error`

---

## 🧰 Tool overview

| Tool | 역할 |
| ---- | ---- |
| `law_rag_tool` | 국내 법령 RAG — PostgreSQL 정확 매칭 → Qdrant 의미 검색 → 웹 fallback |
| `case_law_rag_tool` | 대법원 판례 검색 (별도 Qdrant 컬렉션) |
| `news_tool` | 산업안전 관련 뉴스 검색·요약 (Tavily) |
| `blog_tool` | 블로그 콘텐츠 검색·요약 (Tavily) |
| `websearch_tool` | 외국 법령 / 일반 웹 검색 |
| `db_query_tool_async` | chat_history 등 DB 직접 조회 (세션 격리 적용) |
| `general_tool` | 법령 외 일반 대화 |

각 Tool 은 `ToolChunk` 를 `yield` 하며 `routes.run_tool` 이 SSE 응답으로 변환합니다.

---

## 🧪 Testing & evaluation

```bash
# 단위 테스트 (mock 기반 — 실제 API/DB 호출 없음)
pip install pytest pytest-asyncio
python -m pytest tests/ -v

# 평가 하네스 (실제 API/DB 필요)
pip install -r eval/requirements-eval.txt
python -m eval.harness              # 베이스라인 + 회귀 + smoke
python -m eval.eval_router          # 라우터 정확도
python -m eval.eval_retrieval       # 검색 Top-k recall
python -m eval.eval_hallucination   # 할루시네이션 검사
python -m eval.load_test            # 동시 접속 부하테스트
python -m eval.fault_inject         # 의존성 장애 주입
```

CI(`.github/workflows/ci.yml`)는 push/PR마다 백엔드 pytest 와 프론트 typecheck/build 를 돌립니다.
현재 테스트 68개, 실측 결과는 [루트 README](../README.md#평가-파이프라인)에 있습니다.

---

## 🧰 Development tips

- **Python**: 3.11+ (CI는 3.11)
- **로그**: `logs/<YYYY-MM-DD>/` 에 chat/server/error 로그 생성
- **핫리로드**: `uvicorn app.main:app --reload`
- **동시성**: SQLAlchemy 풀(`pool_size=10, max_overflow=20`) + SSE 비동기 루프 + Tool 별 async 호출.
  20명 동시 요청 무실패를 실측했습니다.

---

## 🧯 Troubleshooting

| 증상 | 확인 사항 |
| ---- | -------- |
| OpenAI 에러 | `OPENAI_API_KEY`, 프로젝트 권한, 사용량 한도 |
| Qdrant 검색 실패 | `QDRANT_HOST`/`QDRANT_PORT`, 컬렉션 이름, 임베딩 차원(3072) |
| DB 연결 오류 | PostgreSQL 접속 정보·권한, `asyncpg` 설치 여부 |
| SSE 끊김 | 프록시에서 `Cache-Control: no-cache`, `Connection: keep-alive` 헤더 유지 여부 |
| `/api/admin/*` 가 503 | `ADMIN_API_KEY` 미설정 (의도된 fail-closed 동작) |
| 임베딩 캐시 오류 | `.cache` 디렉토리 권한, SQLite 파일 권한 |

---

## 📦 배포

`Dockerfile` 과 저장소 루트의 `docker-compose.yml` 로 컨테이너 배포합니다. 자세한 절차는 `../DEPLOYMENT.md` 참고.

Reverse proxy(Nginx/Caddy) 뒤에 둘 경우 `/api/ask` 경로는 SSE 헤더
(`Cache-Control: no-cache`, `Connection: keep-alive`, 버퍼링 비활성)를 유지하도록 설정하세요.

---

## 📝 라이선스

MIT — 저장소 루트 [LICENSE](../LICENSE) 참고.
