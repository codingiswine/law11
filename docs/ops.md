# 운영 모니터링 상세

루트 [README](../README.md#운영-모니터링)에서 옮겨온 전체 문서입니다. 관리자 엔드포인트 인증은 [api.md](api.md) 참고.

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
