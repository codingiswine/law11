"""레이트리밋 회귀 테스트 (#65).

/api/ask 는 인증 없이 열려 있고 한 번 호출에 GPT 생성 + 임베딩 + 최악의
경우 웹 검색 20초를 쓴다. 한도가 없으면 서버가 죽기 전에 OpenAI·Tavily
요금이 먼저 터진다 — 가용성보다 비용이 먼저 무너지는 DoS다.
"""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.rate_limit import limiter


@pytest.fixture
def client():
    """실제 앱의 배선(main.py)과 같은 구성으로 최소 앱을 만든다.
    실앱을 띄우면 lifespan에서 스케줄러·DB가 붙으므로 단위 테스트엔 과하다."""
    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.post("/ask")
    @limiter.limit("10/minute")
    async def ask(request: Request):
        return {"ok": True}

    with TestClient(app) as c:
        yield c
    limiter.reset()


def test_한도_내_요청은_통과한다(client):
    for i in range(10):
        assert client.post("/ask").status_code == 200, f"{i+1}번째에서 막힘"


def test_한도_초과_요청은_429로_차단된다(client):
    for _ in range(10):
        client.post("/ask")
    r = client.post("/ask")
    assert r.status_code == 429, r.text


def test_설정값이_환경변수로_조절_가능하다():
    """운영에서 한도를 바꾸려고 코드를 고치게 되면 안 된다."""
    from app.config import settings
    assert settings.RATE_LIMIT_ASK
    assert settings.RATE_LIMIT_DEFAULT
    assert isinstance(settings.RATE_LIMIT_ENABLED, bool)
