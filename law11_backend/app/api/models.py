from pydantic import BaseModel, Field
from typing import Optional

class QueryRequest(BaseModel):
    # ⚠️ 길이 제한이 없으면 거대한 본문이 그대로 임베딩·GPT 호출로 들어가
    # 비용 증폭/DoS 경로가 된다 (인증도 rate limit도 없는 상태라 더 그렇다).
    # 법령 질문은 1000자면 충분하고, 초과 시 FastAPI가 422로 거른다.
    question: str = Field(..., max_length=1000)
    search_mode: str = "general" # "general" or "law"
    session_id: Optional[str] = None

class FeedbackRequest(BaseModel):
    message_id: int
    value: int  # 1 = thumbs up, -1 = thumbs down
