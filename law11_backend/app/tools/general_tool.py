from app.config import settings
from core.stream import ToolChunk


async def run(plan):
    query = plan.args.get("query", "")
    yield ToolChunk(type="status", payload=f"💬 일반 대화 시작: {query}")

    system_msg = """너는 산업안전보건 법령 전문 어시스턴트 Law11야.
너의 목표는 사용자의 질문 의도를 파악해, 이전 대화의 맥락을 반영해
자연스럽고 실무에 도움이 되는 방식으로 대답하는 것이야.

규칙:
1️⃣ 이전 대화 내용을 참고해 문맥상 연결된 답변을 해.
2️⃣ 불확실한 부분은 "확인 필요"라고 말해.
3️⃣ 너무 장황하지 않게 3~6줄 이내로 대답해.
4️⃣ 가능한 한 실무적·사실적 근거를 들어 설명해.
"""

    try:
        stream = await settings.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"[이전 대화 및 질문]\n{query}"},
            ],
            temperature=0.5,
            max_tokens=800,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield ToolChunk(type="text", payload=delta)

        yield ToolChunk(type="status", payload="✅ 일반 대화 완료")

    except Exception as e:
        yield ToolChunk(type="error", payload=f"❌ [GeneralTool] 오류: {str(e)}")
