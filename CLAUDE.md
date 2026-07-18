# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Law11 프로젝트 전용 규칙

### 아키텍처 이해

요청 흐름: `POST /api/ask` → `question_router.detect_tool()` → `ToolPlan` → `run_tool()` → 각 tool의 `run(plan)` → `StreamingResponse` (SSE)

스트리밍 단위는 `core/stream.py`의 `ToolChunk`다. `type`은 `"status" | "text" | "source" | "meta" | "error"` 중 하나여야 한다. `"meta"` 청크는 SSE 클라이언트에 전달되지 않고 `qa_logger.log_request()`로만 위임된다.

RAG 검색 우선순위는 반드시 이 순서를 따른다:
1. PostgreSQL `law_chunks` 테이블 (정확한 조문 검색)
2. Qdrant `laws` 컬렉션 (벡터 유사도, threshold=0.45/0.5)
3. Web fallback (`websearch_tool.summarize_web`)

### 수정 금지 핵심 변수

| 변수/필드 | 위치 | 이유 |
|---|---|---|
| `SYSTEM_PROMPT` | `app/tools/law_rag_tool.py` | 할루시네이션 방지 프롬프트 — 임의 수정 시 답변 품질 직결 |
| `law_name_norm`, `article_number_norm` | `init.sql`, `law_rag_tool.py` | PG ↔ Qdrant 조인 키 — 변경 시 검색 전체 깨짐 |
| `_llm_cache` | `app/services/question_router.py` | 모듈 수준 dict — 재생성하면 캐시 무효화 |
| `meta` ToolChunk | `routes.py` event_stream | `qa_logger`로만 가야 함 — SSE로 유출 금지 |

### 설정 변경 규칙

- `app/config/settings.py`에서 `openai_client`, `qdrant_client`, `async_engine`을 생성한다. 다른 파일에서 이 세 클라이언트를 **새로 생성하지 않는다** — `settings.*`로 가져다 쓴다.
- `.env` 파일 경로: Docker는 `/app/.env`, 로컬은 `law11_backend/.env`. `ENV_PATH` 자동 감지 로직을 손대지 않는다.
- Qdrant 컬렉션명은 `.env`의 `QDRANT_COLLECTION_NAME`으로만 제어한다. 코드에 `"laws"` 하드코딩 금지.

### Tool 추가/수정 규칙

- 새 tool을 추가하면 반드시 세 곳을 동시에 수정한다:
  1. `app/tools/<new_tool>.py` — `async def run(plan)` 구현 (`ToolChunk` yield)
  2. `app/api/routes.py`의 `tool_map` dict
  3. `app/services/question_router.py`의 `_LLM_SYSTEM` 도구 목록 + `valid` set
- `QuestionRouter`의 fast-path 키워드 리스트(`law_keywords`, `foreign_keywords` 등)를 수정할 때는 `_classify_with_llm`의 `valid` set과 일관성을 유지한다.

### DB 스키마 규칙

- `article_number_norm` 스킴은 `"N"`(본조) 또는 `"N의M"`(가지조문, 예: 제14조의2 → `"14의2"`)이다. 수집(`law_updater_async`)과 조회(`law_rag_tool.normalize_article`)가 반드시 같은 스킴을 유지해야 한다 — 한쪽만 바꾸면 조문 소실/오매칭이 재발한다 (README #28). 표시형 변환은 `law_rag_tool.article_display()` 사용.
- `chat_history` 테이블의 `metadata` 컬럼은 JSONB다. tool 이름은 `metadata->>'tool'`로 조회한다. `save_chat_history()`에서 `plan.tool.split("_")[0]`으로 단축 저장하므로 tool 이름 비교 시 이 점을 고려한다.
- `law_chunks`에 새 컬럼을 추가할 경우 반드시 `init.sql`과 `app/tools/law_updater_async.py` INSERT 쿼리를 함께 수정한다.

### eval 파이프라인 규칙

성공 기준은 다음 파일/명령으로 검증한다:

```
# 베이스라인 측정 (전체 30케이스)
cd law11_backend && python -m eval.harness

# 회귀 테스트 (직전 결과와 비교, 5% 이상 하락 시 exit 1)
python -m eval.harness --compare

# 빠른 확인 (5케이스 smoke)
python -m eval.harness --smoke

# 라우터 정확도
python -m eval.eval_router

# 검색 성능 (top-k 비교)
python -m eval.eval_retrieval

# 할루시네이션 검사
python -m eval.eval_hallucination

# 멀티턴 회귀 (백엔드가 localhost:8000에 떠 있어야 함, 로컬 실행 시 docker 백엔드 컨테이너 중지 확인)
python -m eval.eval_multiturn
```

- `eval/golden_dataset.json` — 30개 골든 케이스. 필드: `id`, `question_type`, `law_name`, `law_name_norm`, `article_number`, `article_number_norm`, `question`, `ground_truth`. 케이스 추가/삭제는 `eval/seed_golden_dataset.py`로 재생성하고, `ground_truth` 핵심 요약은 수동 편집한다.
- `eval/logs/qa_YYYYMMDD.jsonl` — `qa_logger.log_request()`가 기록하는 운영 로그. `perf_report.py`의 입력 소스. 삭제 금지.
- `eval/results/baseline_*.json` — `harness.py`의 출력. `--compare` 모드의 기준점. 커밋하지 않는다.

### 스케줄러 / 비동기 규칙

- `law_scheduler.py`의 `start_scheduler()` / `stop_scheduler()`는 `app/main.py` lifespan에서만 호출한다.
- APScheduler job id는 `"weekly_law_update"` 고정. 중복 등록 방지를 위해 `replace_existing=True`를 반드시 유지한다.
- `AsyncQdrantClient`는 `await qdrant.search(collection, vector, ...)` 시그니처를 사용한다 (`query_vector=` 키워드 없이 위치 인자). 변경하지 않는다.

### 로컬 실행 환경

```bash
# Python 가상환경 (항상 이 경로 사용)
source /Users/daniel/Desktop/projects/law11/.venv/bin/activate

# 백엔드 단독 실행
cd law11_backend && uvicorn app.main:app --reload --port 8000

# 전체 스택 (Docker)
docker compose up --build
```

venv는 `law11_backend/.venv`가 아니라 프로젝트 루트 `/Users/daniel/Desktop/projects/law11/.venv`에 있다.
