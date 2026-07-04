# Law11 — 데이터 모델

> 이 문서는 Law11에서 다루는 핵심 데이터의 구조를 정의합니다.

---

## 전체 구조

```
[LawChunk] ←─ 검색 대상 ─────────────────────────────┐
                                                      │
[ChatSession] ──1:N──→ [ChatMessage] ──1:N──→ [Citation]
                            │                     │
                            └── tool, role        └── law_chunk 참조 (조문 원문)
```

---

## 엔티티 상세

### LawChunk (법령 조문 단위)
법령 원문을 조문 단위로 쪼갠 검색 대상. PostgreSQL `law_chunks` 테이블 + Qdrant `laws` 컬렉션에 이중 저장된다.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 고유 식별자 (UUID) | `a1b2c3d4-...` | O |
| law_name | 법령 원문명 | `주택임대차보호법` | O |
| law_name_norm | 정규화된 법령명 (검색 키) | `주택임대차보호법` | O |
| article_number | 조문 번호 원문 | `제3조의2` | O |
| article_number_norm | 정규화된 조문 번호 (검색 키) | `3_2` | O |
| content | 조문 전문 텍스트 | `임대인은 임대차 종료 후...` | O |
| embedding | 벡터 임베딩 (1536차원) | `[0.02, -0.15, ...]` | O |
| updated_at | 마지막 업데이트 일시 | `2026-05-01` | O |

**주의**: `law_name_norm`과 `article_number_norm`은 PostgreSQL↔Qdrant 조인 키. 절대 임의 변경 금지.

---

### ChatSession (대화 세션) — v0.9 추가
한 사용자의 연속된 대화 묶음. Multi-turn을 위해 도입되며 PostgreSQL에 저장한다.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| session_id | 고유 식별자 (UUID, 클라이언트 생성) | `sess_abc123` | O |
| created_at | 세션 시작 시각 | `2026-05-30T10:00:00Z` | O |
| updated_at | 마지막 메시지 시각 | `2026-05-30T10:15:00Z` | O |

---

### ChatMessage (개별 메시지)
세션 내 사용자 질문과 AI 답변 쌍. 현재 `chat_history` 테이블에 저장되며 v0.9에서 session_id 컬럼이 추가된다.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 자동 증가 정수 | `42` | O |
| session_id | 소속 세션 (FK → ChatSession) | `sess_abc123` | X (v0.9 이전 NULL) |
| role | 발화자 | `user` / `assistant` | O |
| content | 메시지 본문 | `전세 보증금 반환 기한은?` | O |
| tool | 사용된 tool 단축명 | `law` / `web` / `mixed` | O |
| metadata | JSONB 추가 정보 | `{"latency_ms": 320}` | X |
| created_at | 메시지 생성 시각 | `2026-05-30T10:01:00Z` | O |

---

### Citation (조문 인용 출처) — v1.0 추가
답변이 참조한 법령 조문의 상세 정보. 신뢰도 점수와 함께 저장되어 UI 카드로 표시된다.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 자동 증가 정수 | `101` | O |
| message_id | 소속 메시지 (FK → ChatMessage) | `42` | O |
| law_name | 인용 법령명 | `주택임대차보호법` | O |
| article_number | 인용 조문 번호 | `제3조의2` | O |
| article_text | 인용 조문 원문 (발췌) | `임대인은 임대차 종료 후...` | O |
| score | 유사도 점수 (0~1) | `0.82` | O |
| created_at | 기록 시각 | `2026-05-30T10:01:01Z` | O |

---

## 관계 요약
- **ChatSession 1 : N ChatMessage** — 한 세션에 여러 메시지
- **ChatMessage 1 : N Citation** — 한 답변에 여러 조문 인용
- **LawChunk ← Citation** — Citation은 LawChunk를 참조하지만 FK 미설정 (law_name_norm으로 소프트 조인)

---

## 왜 이 구조인가

- **이중 저장 (PG + Qdrant)**: 정확한 조문 번호 검색(PG)과 의미 기반 검색(Qdrant)을 동시에 지원하기 위함. 하나만 쓰면 "제3조의2"를 정확히 찾거나 "보증금 반환" 의미를 찾는 것 중 하나만 된다.
- **session_id NULL 허용**: v0.8 기존 레코드와 호환성 유지. 마이그레이션 없이 v0.9 세션 기능 추가 가능.
- **Citation 소프트 조인**: law_name_norm으로 조인하여 LawChunk 테이블 변경 시 Citation에 cascade 없이 독립 운용 가능.

---

## [NEEDS CLARIFICATION]

- [ ] ChatSession 만료 정책 — TTL 몇 시간/일? 만료 시 cascade delete 여부
- [ ] Citation 최대 개수 — 답변당 몇 개까지 저장할지 (현재 상위 3개 추정)
- [ ] LawChunk embedding 차원 — OpenAI text-embedding-3-small (1536) 고정 여부
