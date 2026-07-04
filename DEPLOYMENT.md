# 🚀 Law11 프로덕션 배포 가이드

## 📋 배포 전 체크리스트

### 1. 환경 변수 설정
```bash
cd law11_backend

# .env 파일 생성
cp .env.example .env

# 필수 환경 변수 입력
nano .env
```

**필수 환경 변수:**
- `OPENAI_API_KEY`: OpenAI API 키
- `DB_PASS`: PostgreSQL 비밀번호 (강력한 비밀번호 사용)
- `OPENAI_PROJECT_ID`: (선택) OpenAI 프로젝트 ID

### 2. 보안 체크
```bash
# .gitignore에 .env 포함 확인
grep -q "^\.env$" .gitignore || echo ".env" >> .gitignore

# docker-compose.yml에 평문 비밀번호 제거 확인
grep -i "password.*:" docker-compose.yml | grep -v "\${" && echo "⚠️ 평문 비밀번호 발견!"

# 권한 설정
chmod 600 law11_backend/.env
```

---

## 🐳 Docker 배포

### 프로덕션 환경 실행
```bash
# 1. 환경 변수 export (선택)
export DB_PASS=$(openssl rand -base64 32)
export OPENAI_API_KEY=your-key-here

# 2. Docker Compose로 시작
docker-compose up -d

# 3. 로그 모니터링
docker-compose logs -f fastapi

# 4. 헬스 체크
curl http://localhost:8000/health
```

### 서비스 상태 확인
```bash
# 전체 서비스 상태
docker-compose ps

# 개별 서비스 로그
docker-compose logs postgres
docker-compose logs qdrant
docker-compose logs fastapi

# 컨테이너 리소스 사용량
docker stats
```

---

## 🔧 배포 후 초기 설정

### 1. PostgreSQL 테이블 확인
```bash
docker-compose exec postgres psql -U daniel -d llex -c "\dt"

# 테이블 목록 출력 확인:
# - chat_history
# - law_chunks
```

### 2. Qdrant 컬렉션 확인
```bash
curl http://localhost:6333/collections/laws

# 또는 웹 UI:
open http://localhost:6333/dashboard
```

### 3. API 테스트
```bash
# 헬스 체크
curl http://localhost:8000/health

# 채팅 테스트
curl -X POST "http://localhost:8000/api/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "산업안전보건법이란?"}'

# 메트릭 확인
curl http://localhost:8000/api/metrics/summary
```

---

## 📊 모니터링 설정

### Prometheus 연동 (선택)
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'law11_backend'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/api/metrics'
    scrape_interval: 15s
```

### Grafana 대시보드 (선택)
주요 메트릭:
- `llex_requests_total`: 총 요청 수
- `llex_response_time_seconds`: 응답 시간
- `llex_errors_total`: 에러 수
- `llex_agent_usage_total`: Agent 사용 통계
- `llex_active_requests`: 활성 요청 수

---

## 🔄 무중단 업데이트

### 코드 업데이트
```bash
# 1. 최신 코드 pull
git pull origin main

# 2. FastAPI만 재빌드 (DB는 유지)
docker-compose build fastapi

# 3. 무중단 재시작
docker-compose up -d --no-deps --build fastapi

# 4. 로그 확인
docker-compose logs -f fastapi
```

### 데이터베이스 마이그레이션
```bash
# 1. 백업
docker-compose exec postgres pg_dump -U daniel llex > backup_$(date +%Y%m%d).sql

# 2. 마이그레이션 실행
docker-compose exec postgres psql -U daniel -d llex -f /path/to/migration.sql

# 3. 확인
docker-compose exec postgres psql -U daniel -d llex -c "\d chat_history"
```

---

## 🔐 보안 강화

### 1. SSL/TLS 설정 (Nginx 리버스 프록시)
```nginx
server {
    listen 443 ssl http2;
    server_name llex.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/llex.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/llex.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 지원
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }
}
```

### 2. 방화벽 설정
```bash
# UFW 사용 시
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw deny 5432/tcp   # PostgreSQL (외부 차단)
sudo ufw deny 6333/tcp   # Qdrant (외부 차단)
sudo ufw enable
```

### 3. Docker 네트워크 격리
```yaml
# docker-compose.yml (이미 적용됨)
networks:
  llex_network:
    driver: bridge
    internal: true  # 외부 접근 차단
```

---

## 📈 성능 최적화

### 1. Uvicorn Workers 조정
```yaml
# docker-compose.yml
services:
  fastapi:
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 2. PostgreSQL Connection Pool
```python
# settings.py (이미 적용됨)
pool_size=10
max_overflow=20
pool_pre_ping=True
```

### 3. 임베딩 캐시 영속성
```yaml
# docker-compose.yml (이미 적용됨)
volumes:
  - ./.cache:/app/.cache
```

---

## 🛠️ 트러블슈팅

### 문제: 컨테이너가 시작되지 않음
```bash
# 로그 확인
docker-compose logs --tail=100 fastapi

# 컨테이너 재시작
docker-compose restart fastapi

# 전체 재시작
docker-compose down && docker-compose up -d
```

### 문제: PostgreSQL 연결 실패
```bash
# DB 헬스 체크
docker-compose exec postgres pg_isready -U daniel -d llex

# DB 재시작
docker-compose restart postgres

# 연결 테스트
docker-compose exec fastapi python -c "from app.config import settings; print('DB 연결 성공')"
```

### 문제: Qdrant 컬렉션 없음
```bash
# Qdrant 헬스 체크
curl http://localhost:6333/health

# 컬렉션 확인
curl http://localhost:6333/collections

# 재시작
docker-compose restart qdrant
```

### 문제: 메모리 부족
```bash
# 컨테이너 메모리 제한 설정
# docker-compose.yml에 추가
services:
  fastapi:
    mem_limit: 2g
    mem_reservation: 1g
```

---

## 📊 로그 관리

### 로그 로테이션 설정
```json
# /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
```

### 로그 확인
```bash
# 실시간 로그 (모든 서비스)
docker-compose logs -f

# 특정 서비스 로그
docker-compose logs -f fastapi

# 최근 100줄
docker-compose logs --tail=100 fastapi

# 로그 파일 직접 확인 (앱 레벨)
docker-compose exec fastapi ls -lh /app/logs/
docker-compose exec fastapi tail -f /app/logs/2025-11-06/chat_history.log
```

---

## 🔄 백업 & 복구

### 데이터베이스 백업
```bash
# PostgreSQL 백업
docker-compose exec postgres pg_dump -U daniel llex | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Qdrant 백업 (볼륨 복사)
tar -czf qdrant_backup_$(date +%Y%m%d).tar.gz qdrant_storage/

# 자동 백업 (cron 설정)
0 2 * * * cd /path/to/llex && docker-compose exec postgres pg_dump -U daniel llex | gzip > backups/db_$(date +\%Y\%m\%d).sql.gz
```

### 복구
```bash
# PostgreSQL 복구
gunzip -c backup_20251106.sql.gz | docker-compose exec -T postgres psql -U daniel -d llex

# Qdrant 복구
docker-compose down
rm -rf qdrant_storage/*
tar -xzf qdrant_backup_20251106.tar.gz
docker-compose up -d
```

---

## 🎯 프로덕션 체크리스트

배포 전 반드시 확인:

- [ ] `.env` 파일 설정 완료
- [ ] `DB_PASS` 강력한 비밀번호 설정
- [ ] Docker Compose 헬스 체크 동작 확인
- [ ] SSL/TLS 인증서 설정 (Nginx)
- [ ] 방화벽 규칙 적용
- [ ] 백업 자동화 설정
- [ ] 모니터링 시스템 연동 (Prometheus/Grafana)
- [ ] 로그 로테이션 설정
- [ ] 에러 알림 설정 (Slack/Email)
- [ ] 문서화 완료

---

## 📞 긴급 연락처

- **시스템 관리자**: GitHub Issues
- **긴급 이슈**: GitHub Issues
- **장애 대응**: On-call rotation 참고

---

## 📚 추가 리소스

- [LangGraph Documentation](https://python.langchain.com/docs/langgraph)
- [FastAPI Best Practices](https://fastapi.tiangolo.com/deployment/)
- [Docker Compose Production](https://docs.docker.com/compose/production/)
- [Qdrant Performance Tuning](https://qdrant.tech/documentation/guides/performance/)
