"""레이트리밋 단일 소스 (#65).

main.py와 routes.py가 같은 Limiter 인스턴스를 써야 하는데 routes가 main에
import되므로, 순환 import를 피하려 별도 모듈에 둔다.

키는 클라이언트 IP다. 이 배포에서 nginx는 정적 파일만 서빙하고 /api를
프록시하지 않으므로(law11_frontend/nginx.conf) 실제 클라이언트 IP가 그대로
들어온다. 프록시를 끼우게 되면 X-Forwarded-For 처리를 추가해야 한다 —
그때 신뢰 가능한 프록시 목록 없이 헤더를 믿으면 한 줄로 우회된다.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.RATE_LIMIT_ENABLED,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
)
