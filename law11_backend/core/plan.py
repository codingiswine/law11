# law11_backend/core/plan.py
from typing import Any, Dict
from dataclasses import dataclass, field
import time

@dataclass
class ToolPlan:
    """Router가 생성하는 표준 실행 계획"""
    tool: str                # 예: 'law_rag', 'news', 'general'
    args: Dict[str, Any]     # 실행에 필요한 파라미터
    created_at: float = field(default_factory=time.time)

    def summary(self) -> str:
        return f"ToolPlan(tool={self.tool}, args={list(self.args.keys())})"
