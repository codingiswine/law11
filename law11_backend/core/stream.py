# law11_backend/core/stream.py
from dataclasses import dataclass
from typing import Any, Literal
import json, time

@dataclass
class ToolChunk:
    """툴이 스트리밍 중 반환하는 데이터 조각"""
    type: Literal["status", "text", "source", "error"]
    payload: Any
    at: float = time.time()

    def to_json(self) -> str:
        return json.dumps({
            "event": self.type,
            "payload": self.payload,
            "at": self.at,
        }, ensure_ascii=False)
