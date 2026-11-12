from app.config import settings
from core.logger import law11_logger as logger
from core.stream import ToolChunk


async def run(plan):
    query = plan.args.get("query", "")
    context = plan.args.get("context", "")
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

    # ⚠️ system_msg가 "이전 대화 내용을 참고해"라고 지시하지만, 실제로는
    # plan.args["context"]를 한 번도 읽지 않아 현재 질문만 보냈었다 (websearch_tool
    # 에서 오늘 이미 발견/수정한 것과 같은 버그 클래스). 실측: "비계 설치 안전
    # 기준 알려줘" 다음 "그거 다 지키려니까 진짜 힘들다"를 물으면 "그거"가
    # 비계를 가리키는 걸 몰라 산업안전보건법 전반에 대한 일반론만 답했음.
    user_content = f"[이전 대화 및 질문]\n{context}\n\n{query}" if context else f"[질문]\n{query}"

    try:
        stream = await settings.openai_client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_content},
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
        # ⚠️ 예외 원문을 그대로 내보내면 OpenAI 인증 오류의 키 접두어 같은 내부 정보가
        # SSE로 사용자 화면에 간다. #31/#66은 run_tool 밖으로 raise된 예외만 가렸고,
        # 툴이 직접 yield하는 error 청크는 걸러지지 않았다 (#83). 상세는 로그로만.
        logger.error(f"[GeneralTool 오류] {e}")
        yield ToolChunk(type="error", payload="❌ 처리 중 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
