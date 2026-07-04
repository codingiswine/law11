#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_logger.py
────────────
요청마다 retrieval 메타데이터를 JSONL로 기록한다.
routes.py가 meta ToolChunk를 받으면 여기에 위임한다.

로그 위치: eval/logs/qa_YYYYMMDD.jsonl
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

LOG_DIR = Path(__file__).parent.parent.parent / "eval" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_request(
    query: str,
    query_type: str,            # "direct_article" | "semantic" | "web_fallback"
    selected_source: str,       # "pg" | "qdrant" | "web" | "none"
    selected_articles: List[str],
    fallback_used: bool,
    confidence_score: Optional[float] = None,
    tool: str = "",
) -> None:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "tool": tool,
        "query": query[:300],
        "query_type": query_type,
        "selected_source": selected_source,
        "selected_articles": selected_articles,
        "fallback_used": fallback_used,
        "confidence_score": round(confidence_score, 4) if confidence_score else None,
    }
    today = datetime.now().strftime("%Y%m%d")
    path = LOG_DIR / f"qa_{today}.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
