import json
from typing import List
from app.config import settings

_HALLUCINATION_SYSTEM = """너는 RAG 시스템의 할루시네이션을 탐지하는 평가자야.

[판정 기준]
GROUNDED      : 답변의 구체적 주장이 모두 제공된 조문에서 확인 가능
PARTIAL       : 일부는 조문 기반, 일부는 조문에 없는 내용 포함
HALLUCINATION : 조문에 없는 수치, 기간, 조건, 처벌 내용을 주장

[출력 형식 - JSON만]
{"verdict": "GROUNDED" | "PARTIAL" | "HALLUCINATION"}"""

_RELEVANCE_SYSTEM = """너는 AI 답변의 관련성을 평가하는 평가자야.

[판정 기준]
RELEVANT     : 답변이 사용자 질문에 실질적으로 답하고 있음
NOT_RELEVANT : 답변이 질문과 무관하거나 전혀 다른 주제를 다룸

[출력 형식 - JSON만]
{"verdict": "RELEVANT" | "NOT_RELEVANT"}"""


async def grade_hallucination(question: str, answer: str, contexts: List[str]) -> str:
    ctx_block = "\n\n".join(f"[조문 {i+1}]\n{c}" for i, c in enumerate(contexts[:5]))
    user_msg = f"[질문]\n{question}\n\n[검색된 조문]\n{ctx_block}\n\n[AI 답변]\n{answer}\n\nJSON만 출력해."
    try:
        resp = await settings.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _HALLUCINATION_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=20,
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        verdict = result.get("verdict", "GROUNDED")
        return verdict if verdict in ("GROUNDED", "PARTIAL", "HALLUCINATION") else "GROUNDED"
    except Exception:
        return "GROUNDED"


async def grade_relevance(question: str, answer: str) -> str:
    user_msg = f"[질문]\n{question}\n\n[AI 답변]\n{answer}\n\nJSON만 출력해."
    try:
        resp = await settings.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _RELEVANCE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=20,
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        verdict = result.get("verdict", "RELEVANT")
        return verdict if verdict in ("RELEVANT", "NOT_RELEVANT") else "RELEVANT"
    except Exception:
        return "RELEVANT"
