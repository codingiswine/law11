# Law11 — Phase 분리 계획

> 한 번에 다 만들면 복잡해집니다.
> Phase별로 "진짜 동작하는 제품"을 만들고, 안정화 후 다음 단계로 넘어갑니다.

---

## Phase 1 — v0.8 MVP (완료 ✅)

### 목표
한국 법령 조문을 자연어로 질문하면, RAG 기반으로 실제 법령 원문을 근거로 답변한다.

### 기능
- [x] RAG 조문 검색 (PostgreSQL 정확 매칭 + Qdrant 벡터 검색)
- [x] 질문 라우터 (law / web / mixed 자동 분류)
- [x] 웹 검색 폴백 (DuckDuckGo, 법령 DB 미매칭 시)
- [x] 스트리밍 응답 (SSE — status → text → source 순)
- [x] 법령 주간 자동 업데이트 (APScheduler + 법령정보원 API)
- [x] QA 로거 + eval 파이프라인 (30케이스 골든 데이터셋)

### 데이터
- `LawChunk` (PostgreSQL + Qdrant)
- `ChatMessage` (session_id = NULL)

### "진짜 제품" 체크리스트
- [x] 실제 PostgreSQL + Qdrant 연결 (목업 데이터 X)
- [x] 실제 서버에 배포 가능 (Docker Compose)
- [x] eval 파이프라인으로 품질 측정 가능

### 성공 기준
```bash
cd law11_backend && python -m eval.harness --smoke  # 5케이스 전부 통과
python -m eval.eval_router                          # 라우터 정확도 ≥ 90%
python -m eval.eval_hallucination                   # 할루시네이션 0건
```

---

## Phase 2 — v0.9 Multi-turn (예정: 2026 Q3)

### 전제 조건
- Phase 1 eval 전체 30케이스 통과 안정화

### 목표
"방금 말한 계약서에서..."처럼 이전 대화를 참조하는 후속 질문을 처리한다.

### 기능
- [ ] `ChatSession` 테이블 추가 (`init.sql` 마이그레이션)
- [ ] `chat_history`에 `session_id` 컬럼 추가 (NULL 허용, 기존 호환)
- [ ] 세션 ID를 프론트에서 생성·전달 (`X-Session-ID` 헤더)
- [ ] 이전 N개 메시지를 LLM 컨텍스트에 주입 (`question_router` 수정)
- [ ] 세션 조회/삭제 API (`GET /api/session/{id}`, `DELETE /api/session/{id}`)

### 추가 데이터
- `ChatSession` (신규)
- `ChatMessage.session_id` (기존 컬럼 추가)

### 회귀 테스트
```bash
python -m eval.harness --compare  # Phase 1 대비 5% 이하 하락
```

### Phase 2 시작 프롬프트
```
이 PRD를 읽고 Phase 2 (Multi-turn)를 구현해주세요.
@PRD/01_PRD.md
@PRD/02_DATA_MODEL.md
@PRD/04_PROJECT_SPEC.md

Phase 2 범위:
- ChatSession 테이블 추가 (init.sql)
- chat_history에 session_id 컬럼 추가 (NULL 허용)
- 세션 ID 헤더 처리 (routes.py)
- 이전 대화 컨텍스트 LLM 주입 (question_router.py)
- 세션 관리 API 2개

반드시 지켜야 할 것:
- 04_PROJECT_SPEC.md의 "절대 하지 마" 목록 준수
- 기존 chat_history 레코드 데이터 손실 없음
- eval.harness --compare 통과
```

---

## Phase 3 — v1.0 Citation (예정: 2026 Q4)

### 전제 조건
- Phase 2 Multi-turn 안정 운영 중

### 목표
"어떤 법 몇 조에 근거했는지"를 UI 카드로 명시하여 신뢰도를 높인다.

### 기능
- [ ] `Citation` 테이블 추가
- [ ] `law_rag_tool.py`에서 top-k 조문을 Citation으로 저장
- [ ] LLM 프롬프트에 인용 지시 추가 (`[법령명 제N조]` 형식)
- [ ] 프론트엔드 Source 카드 UI 강화 (법령명 + 조문번호 + 신뢰도 점수)
- [ ] `eval_hallucination.py`에 Citation 검증 로직 추가

### 추가 데이터
- `Citation` (신규)

### 주의사항
- SYSTEM_PROMPT 수정 시 eval_hallucination 재측정 필수
- Citation 카드 UI는 모바일 반응형 필수

### Phase 3 시작 프롬프트
```
이 PRD를 읽고 Phase 3 (Citation)을 구현해주세요.
@PRD/01_PRD.md
@PRD/02_DATA_MODEL.md
@PRD/04_PROJECT_SPEC.md

Phase 3 범위:
- Citation 테이블 추가
- law_rag_tool.py Citation 저장
- LLM 프롬프트 인용 형식 추가
- 프론트엔드 Source 카드 UI

반드시 지켜야 할 것:
- SYSTEM_PROMPT 수정 후 eval_hallucination 재실행
- Citation 카드 모바일 반응형
- eval.harness --compare 통과
```

---

## Phase 4 — v1.1 Reranking (예정: 2027 Q1)

### 전제 조건
- Phase 1~3 안정 운영 중
- BGE-reranker 모델 서빙 환경 준비 (CPU 최소 사양 확인)

### 목표
Qdrant 벡터 검색 후 Cross-encoder로 재순위하여 top-1 정답률을 높인다.

### 기능
- [ ] `BAAI/bge-reranker-v2-m3` 모델 로컬 로드 (transformers)
- [ ] `law_rag_tool.py`에 reranking 레이어 삽입 (Qdrant 결과 후처리)
- [ ] top-k 허용치 동적 조정 (reranker 점수 기반 threshold)
- [ ] `eval_retrieval.py`에 reranking 전/후 비교 지표 추가
- [ ] A/B 테스트 플래그 (env: `USE_RERANKER=true/false`)

### 주의사항
- GPU 없을 경우 응답 지연 증가 (CPU 추론 시 ~500ms 추가)
- `AsyncQdrantClient` 시그니처 변경 금지 (`await qdrant.search(collection, vector, ...)`)
- reranker 모델 파일 Docker 이미지에 포함 시 이미지 크기 ~1.5GB 증가

### Phase 4 시작 프롬프트
```
이 PRD를 읽고 Phase 4 (Reranking)를 구현해주세요.
@PRD/01_PRD.md
@PRD/04_PROJECT_SPEC.md
@docs/superpowers/specs/2026-05-21-rag-reranking-design.md

Phase 4 범위:
- BGE-reranker-v2-m3 모델 로드 및 재순위
- law_rag_tool.py reranking 레이어 추가
- eval_retrieval.py 비교 지표 추가
- USE_RERANKER env 플래그

반드시 지켜야 할 것:
- AsyncQdrantClient 시그니처 변경 금지
- eval.harness --compare 통과 (reranker ON 기준)
```

---

## Phase 로드맵 요약

| Phase | 버전 | 핵심 기능 | 상태 |
|-------|------|----------|------|
| Phase 1 | v0.8 | RAG 조문 검색 + 라우터 + 스트리밍 | ✅ 완료 |
| Phase 2 | v0.9 | Multi-turn 대화 맥락 유지 | 예정 (2026 Q3) |
| Phase 3 | v1.0 | 조문 인용 강화 (Citation 카드) | 예정 (2026 Q4) |
| Phase 4 | v1.1 | BGE Reranking 정확도 강화 | 예정 (2027 Q1) |
