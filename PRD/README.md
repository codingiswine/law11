# Law11 — 디자인 문서

> Show Me The PRD로 생성됨 (2026-05-30)

## 문서 구성

| 문서 | 내용 | 언제 읽나 |
|------|------|----------|
| [01_PRD.md](./01_PRD.md) | 뭘 만드는지, 누가 쓰는지, 성공 기준 | 프로젝트 시작 전, 포트폴리오 설명 시 |
| [02_DATA_MODEL.md](./02_DATA_MODEL.md) | 데이터 구조 (LawChunk, ChatSession, ChatMessage, Citation) | DB 설계·수정할 때 |
| [03_PHASES.md](./03_PHASES.md) | v0.8→v0.9→v1.0→v1.1 단계별 계획 + 시작 프롬프트 | 다음 기능 개발 시작할 때 |
| [04_PROJECT_SPEC.md](./04_PROJECT_SPEC.md) | AI 행동 규칙, 절대 금지 목록, 환경변수 | AI에게 코드 시킬 때마다 함께 공유 |

## 현재 상태

**v0.8 완료** — RAG 조문 검색, 질문 라우터, 스트리밍 응답, 법령 자동 업데이트

## 다음 단계

Phase 2 (v0.9 Multi-turn)를 시작하려면 [03_PHASES.md](./03_PHASES.md)의 **"Phase 2 시작 프롬프트"**를 복사해서 Claude Code에 붙여넣으세요.

## 미결 사항 종합

- [ ] ChatSession 만료 정책 (TTL 미정)
- [ ] Citation 카드 UI 모바일 레이아웃 확정
- [ ] Reranker 모델 서빙 방식 (Docker 포함 vs 별도 서버)
- [ ] 법률 면책 고지 표시 위치
- [ ] LawChunk embedding 차원 고정 여부
