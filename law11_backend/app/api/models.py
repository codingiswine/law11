from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class QueryRequest(BaseModel):
    question: str
    search_mode: str = "general" # "general" or "law"
    session_id: Optional[str] = None

class Source(BaseModel):
    domain: str
    title: str
    summary: str
    link: str
    relevance: float

class AskResponse(BaseModel):
    answer: str
    sources: Optional[List[Source]] = None

class FeedbackRequest(BaseModel):
    message_id: int
    value: int  # 1 = thumbs up, -1 = thumbs down
