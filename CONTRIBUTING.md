# 개발 환경

루트 [README](README.md)에서 옮겨온 로컬 실행·테스트 가이드입니다. 배포는 [DEPLOYMENT.md](DEPLOYMENT.md), 운영 명령은 [docs/ops.md](docs/ops.md) 참고.

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

## 환경 변수

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
