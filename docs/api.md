# Law11 API 레퍼런스

루트 [README](../README.md)에서 옮겨온 전체 엔드포인트 문서입니다. Swagger: http://localhost:8000/docs

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

브라우저에서 <http://localhost:8000/api/dashboard> 접속. 자세한 내용은 [운영 모니터링](ops.md) 참고.

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
