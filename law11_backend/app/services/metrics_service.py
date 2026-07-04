#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metrics_service.py
────────────────────────────────────────────
✅ MLOps 메트릭 수집 및 모니터링 시스템
- Prometheus 메트릭 수집
- 응답 시간, 토큰 사용량, 에러율 추적
- Agent별 사용 통계
────────────────────────────────────────────
"""
import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from contextlib import asynccontextmanager

logger = logging.getLogger("MetricsService")

# ─────────────────────────────
# 📊 Prometheus Metrics 정의
# ─────────────────────────────

# 요청 카운터
request_counter = Counter(
    'law11_requests_total',
    'Total number of requests',
    ['endpoint', 'agent_type', 'status']
)

# 응답 시간 히스토그램
response_time_histogram = Histogram(
    'law11_response_time_seconds',
    'Response time in seconds',
    ['endpoint', 'agent_type'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

# 토큰 사용량
token_usage_counter = Counter(
    'law11_tokens_used_total',
    'Total tokens used',
    ['agent_type', 'model']
)

# 에러 카운터
error_counter = Counter(
    'law11_errors_total',
    'Total errors',
    ['endpoint', 'error_type']
)

# Agent 사용 카운터
agent_usage_counter = Counter(
    'law11_agent_usage_total',
    'Agent usage count',
    ['agent_type']
)

# 동시 활성 요청 수
active_requests_gauge = Gauge(
    'law11_active_requests',
    'Number of active requests',
    ['endpoint']
)


# ─────────────────────────────
# 🎯 메트릭 수집 클래스
# ─────────────────────────────
class MetricsCollector:
    """메트릭 수집 및 관리 클래스"""

    def __init__(self):
        self.start_time = time.time()
        self.total_requests = 0
        self.total_errors = 0

    def record_request(self, endpoint: str, agent_type: str, status: str = "success"):
        """요청 기록"""
        request_counter.labels(endpoint=endpoint, agent_type=agent_type, status=status).inc()
        self.total_requests += 1
        logger.info(f"📊 [Metrics] Request recorded: {endpoint} / {agent_type} / {status}")

    def record_response_time(self, endpoint: str, agent_type: str, duration: float):
        """응답 시간 기록"""
        response_time_histogram.labels(endpoint=endpoint, agent_type=agent_type).observe(duration)
        logger.info(f"⏱️ [Metrics] Response time: {duration:.2f}s ({endpoint}/{agent_type})")

    def record_token_usage(self, agent_type: str, model: str, tokens: int):
        """토큰 사용량 기록"""
        token_usage_counter.labels(agent_type=agent_type, model=model).inc(tokens)
        logger.info(f"🎫 [Metrics] Token usage: {tokens} ({agent_type}/{model})")

    def record_error(self, endpoint: str, error_type: str):
        """에러 기록"""
        error_counter.labels(endpoint=endpoint, error_type=error_type).inc()
        self.total_errors += 1
        logger.error(f"❌ [Metrics] Error recorded: {endpoint} / {error_type}")

    def record_agent_usage(self, agent_type: str):
        """Agent 사용 기록"""
        agent_usage_counter.labels(agent_type=agent_type).inc()
        logger.info(f"🤖 [Metrics] Agent used: {agent_type}")

    @asynccontextmanager
    async def track_request(self, endpoint: str, agent_type: str = "unknown"):
        """요청 추적 컨텍스트 매니저"""
        active_requests_gauge.labels(endpoint=endpoint).inc()
        start_time = time.time()

        try:
            yield
            duration = time.time() - start_time
            self.record_response_time(endpoint, agent_type, duration)
            self.record_request(endpoint, agent_type, "success")
        except Exception as e:
            duration = time.time() - start_time
            self.record_response_time(endpoint, agent_type, duration)
            self.record_request(endpoint, agent_type, "error")
            self.record_error(endpoint, type(e).__name__)
            raise
        finally:
            active_requests_gauge.labels(endpoint=endpoint).dec()

    def get_summary(self) -> Dict[str, Any]:
        """메트릭 요약 정보"""
        uptime = time.time() - self.start_time
        return {
            "uptime_seconds": uptime,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate": self.total_errors / max(self.total_requests, 1),
            "timestamp": datetime.now().isoformat()
        }


# ─────────────────────────────
# 🌐 Global Metrics Collector
# ─────────────────────────────
metrics_collector = MetricsCollector()


# ─────────────────────────────
# 📈 Prometheus 메트릭 엔드포인트
# ─────────────────────────────
def get_prometheus_metrics():
    """Prometheus 메트릭 반환"""
    return generate_latest()


__all__ = [
    "metrics_collector",
    "get_prometheus_metrics",
    "MetricsCollector",
    "CONTENT_TYPE_LATEST"
]

print("✅ [init] metrics_service.py 로드 완료")
