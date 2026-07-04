# 베이스 이미지
FROM python:3.11-slim

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y build-essential curl && apt-get clean

# 작업 디렉토리
WORKDIR /app

# requirements.txt 복사 및 설치
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 앱 코드 복사
COPY ./app /app/app
COPY ./core /app/core

# ✅ 핵심 추가: Python import 루트 지정
ENV PYTHONPATH=/app

# ✅ LangChain deprecation warning 숨기기
ENV PYTHONWARNINGS="ignore::DeprecationWarning"

# FastAPI 실행 명령어
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
