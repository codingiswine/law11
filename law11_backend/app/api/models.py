from pydantic import BaseModel
from typing import Optional

class QueryRequest(BaseModel):
    question: str
    search_mode: str = "general" # "general" or "law"
    session_id: Optional[str] = None

class FeedbackRequest(BaseModel):
    message_id: int
    value: int  # 1 = thumbs up, -1 = thumbs down
