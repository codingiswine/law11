import re, json, asyncio, time
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, Response
from typing import AsyncGenerator, List, Optional
from sqlalchemy import text

# ✅ Docker 기준으로 경로 수정
from app.config import settings
from app.api.models import QueryRequest, FeedbackRequest
from app.services.question_router import detect_tool as _detect_tool
from app.services import qa_logger
from app.services.langgraph_multi_agent import run_multi_agent
from app.services.metrics_service import metrics_collector, get_prometheus_metrics, CONTENT_TYPE_LATEST
from core.logger import law11_logger as logger
from core.stream import ToolChunk

# ✅ 비동기 엔진
async_engine = settings.async_engine

# ✅ Tool 모듈 로드
from app.tools import (
    law_rag_tool,
    news_tool,
    blog_tool,
    general_tool,
    db_query_tool_async,
    websearch_tool,
)
from app.tools.law_rag_tool import normalize_law_name, normalize_article

router = APIRouter()

# ─────────────────────────────
# ⚙️ 품질 평가
# ─────────────────────────────
def evaluate_answer_quality(answer: str) -> dict:
    law_refs = re.findall(r"「.*?」", answer)
    article_refs = re.findall(r"제\d+조", answer)
    score = min(len(law_refs) * 10 + len(article_refs) * 5 + 35, 100)
    return {"score": score, "law_ref_count": len(law_refs)}


# ─────────────────────────────
# 💾 비동기 DB 저장
# ─────────────────────────────
async def save_chat_history(user_id: str, question: str, answer: str, tool: str, session_id: Optional[str] = None) -> int:
    eval_ = evaluate_answer_quality(answer)
    effective_session = session_id or "law11_session"
    turn_index = int(time.time())
    metadata_json = json.dumps({"tool": tool})

    insert_row = text("""
        INSERT INTO chat_history (session_id, turn_index, role, content, user_id, metadata, score)
        VALUES (:session_id, :turn_index, :role, :content, :user_id, :metadata, :score)
    """)
    insert_assistant = text("""
        INSERT INTO chat_history (session_id, turn_index, role, content, user_id, metadata, score)
        VALUES (:session_id, :turn_index, :role, :content, :user_id, :metadata, :score)
        RETURNING id
    """)

    try:
        async with async_engine.begin() as conn:
            await conn.execute(insert_row, {
                "session_id": effective_session, "turn_index": turn_index,
                "role": "user", "content": question, "user_id": user_id,
                "metadata": metadata_json, "score": eval_["score"]
            })
            result = await conn.execute(insert_assistant, {
                "session_id": effective_session, "turn_index": turn_index + 1,
                "role": "assistant", "content": answer, "user_id": user_id,
                "metadata": metadata_json, "score": eval_["score"]
            })
            assistant_id = result.scalar_one()
        logger.info(f"💾 [DB 저장 완료] {tool} ({eval_['score']}점) id={assistant_id}")
        return assistant_id
    except Exception as e:
        logger.error(f"⚠️ [DB 저장 실패] {e}")
        raise


async def save_citations(assistant_id: int, citations: List[dict]) -> None:
    """Citations를 DB에 저장. 오류 발생 시 무시."""
    if not citations:
        return
    sql = text("""
        INSERT INTO citations (chat_history_id, law_name, article_number, score, rank)
        VALUES (:chat_history_id, :law_name, :article_number, :score, :rank)
    """)
    try:
        async with async_engine.begin() as conn:
            for c in citations:
                await conn.execute(sql, {
                    "chat_history_id": assistant_id,
                    "law_name": c.get("law_name", ""),
                    "article_number": c.get("article_number", ""),
                    "score": c.get("score"),
                    "rank": c.get("rank"),
                })
    except Exception as e:
        logger.error(f"⚠️ [Citation 저장 실패] {e}")


# ─────────────────────────────
# 🧠 Tool 실행기 (비동기)
# ─────────────────────────────
async def run_tool(plan) -> AsyncGenerator[ToolChunk, None]:
    tool = plan.tool
    args = plan.args
    logger.info(f"🔧 [Tool 실행] {tool} ← {args}")

    tool_map = {
        "law_rag_tool": law_rag_tool,
        "news_tool": news_tool,
        "blog_tool": blog_tool,
        "websearch_tool": websearch_tool,
        "db_query_tool_async": db_query_tool_async,
        "general_tool": general_tool,
    }

    # ✅ Tool 존재 여부 확인
    if tool not in tool_map:
        yield ToolChunk(type="error", payload=f"Unknown tool: {tool}")
        return

    # Tool 실행 — law_rag_tool은 내부에서 web fallback을 자체 처리함
    try:
        async for chunk in tool_map[tool].run(plan):
            yield chunk

    except Exception as e:
        yield ToolChunk(type="error", payload=f"❌ Tool 실행 중 오류: {str(e)}")
        logger.error(f"[Tool 오류] {tool}: {e}")
        return


# ─────────────────────────────
# 🚀 FastAPI 엔드포인트 (완전 async)
# ─────────────────────────────
# 🚀 FastAPI 엔드포인트 (완전 async)
@router.post("/ask")
async def ask_law11(request: QueryRequest):
    """질문 → Router → ToolPlan → Tool 실행 → Stream"""
    user_id = "law11_user"
    session_id = request.session_id
    logger.info(f"🚀 [요청 수신] {request.question}")

    try:
        # ① ToolPlan 생성
        plan = await _detect_tool(user_id, request.question, session_id)
        full_answer_parts: List[str] = []

        # ✅ 내부 event_stream 정의
        async def event_stream():
            logger.info(f"🌊 [스트리밍 시작] {plan.summary()}")
            pending_citations: List[dict] = []
            counter = 0

            async for chunk in run_tool(plan):
                # meta 청크는 로깅 전용 — SSE 클라이언트에 전달하지 않음
                if chunk.type == "meta":
                    p = chunk.payload
                    qa_logger.log_request(
                        query=request.question,
                        query_type=p.get("query_type", ""),
                        selected_source=p.get("selected_source", ""),
                        selected_articles=p.get("selected_articles", []),
                        fallback_used=p.get("fallback_used", False),
                        confidence_score=p.get("confidence_score"),
                        tool=p.get("tool", plan.tool),
                    )
                    if p.get("citations"):
                        pending_citations = p["citations"]
                    continue

                # ✅ 항상 JSON 포맷으로 전송
                yield f"data: {json.dumps({'event': chunk.type, 'payload': chunk.payload})}\n\n"

                if chunk.type == "text":
                    full_answer_parts.append(chunk.payload)
                    counter += 1
                    # 🔹 CPU 부하 완화
                    if counter % 20 == 0:
                        await asyncio.sleep(0)

            # ✅ DB 저장
            final_tool_name = plan.tool.split("_")[0]
            full_answer = "".join(full_answer_parts)
            try:
                assistant_id = await save_chat_history(user_id, request.question, full_answer, final_tool_name, session_id=session_id)
                await save_citations(assistant_id, pending_citations)
                yield f"data: {json.dumps({'event': 'saved', 'payload': str(assistant_id)})}\n\n"
                yield f"data: {ToolChunk(type='status', payload='✅ 대화 저장 완료').to_json()}\n\n"
            except Exception as e:
                logger.error(f"⚠️ [DB 저장 중 오류] {e}")
                yield f"data: {ToolChunk(type='error', payload='⚠️ 대화 저장 실패 (DB 연결 문제)').to_json()}\n\n"

        # ✅ 스트리밍 반환
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"❌ [백엔드 에러] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────
# 📜 대화 기록 조회 API
# ─────────────────────────────

@router.get("/history")
async def get_chat_history(
    user_id: str = "law11_user",
    limit: int = 50
):
    """대화 기록 조회"""
    sql = text("""
        SELECT
            id,
            session_id,
            role,
            content,
            metadata,
            score,
            created_at
        FROM chat_history
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        LIMIT :limit
    """)

    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(sql, {"user_id": user_id, "limit": limit})
            rows = result.fetchall()

            history = []
            for row in rows:
                history.append({
                    "id": row.id,
                    "session_id": row.session_id,
                    "role": row.role,
                    "content": row.content,
                    "tool": row.metadata.get("tool") if row.metadata else None,
                    "score": row.score,
                    "created_at": row.created_at.isoformat()
                })

            return {"total": len(history), "history": history}
    except Exception as e:
        logger.error(f"⚠️ [History 조회 실패] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/stats")
async def get_history_stats():
    """대화 통계"""
    sql = text("""
        SELECT
            metadata->>'tool' as tool,
            COUNT(*) as count,
            AVG(score) as avg_score,
            MAX(created_at) as last_used
        FROM chat_history
        WHERE role = 'assistant'
        GROUP BY metadata->>'tool'
        ORDER BY count DESC
    """)

    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(sql)
            rows = result.fetchall()

            stats = []
            for row in rows:
                stats.append({
                    "tool": row.tool,
                    "count": row.count,
                    "avg_score": round(row.avg_score, 1) if row.avg_score else 0,
                    "last_used": row.last_used.isoformat() if row.last_used else None
                })

            return {"stats": stats}
    except Exception as e:
        logger.error(f"⚠️ [Stats 조회 실패] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """대화 기록 대시보드 (HTML)"""
    return """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Law11 대화 기록 대시보드</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <!-- Header -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h1 class="text-4xl font-bold text-gray-800 mb-2">💬 Law11 대화 기록</h1>
            <p class="text-gray-600">실시간 대화 분석 및 품질 모니터링</p>
        </div>

        <!-- Stats Cards -->
        <div class="mb-8">
            <h2 class="text-2xl font-bold text-gray-800 mb-4">📊 Tool 사용 통계</h2>
            <div id="stats" class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4">
                <div class="bg-white p-6 rounded-lg shadow-md animate-pulse">
                    <div class="h-4 bg-gray-200 rounded w-3/4 mb-4"></div>
                    <div class="h-8 bg-gray-200 rounded w-1/2"></div>
                </div>
            </div>
        </div>

        <!-- Chat History -->
        <div>
            <h2 class="text-2xl font-bold text-gray-800 mb-4">💭 최근 대화</h2>
            <div id="history" class="space-y-4">
                <div class="bg-white p-6 rounded-lg shadow-md animate-pulse">
                    <div class="h-4 bg-gray-200 rounded w-full mb-2"></div>
                    <div class="h-4 bg-gray-200 rounded w-5/6"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Tool 색상 매핑
        const toolColors = {
            'law': 'bg-blue-100 text-blue-800',
            'general': 'bg-green-100 text-green-800',
            'news': 'bg-purple-100 text-purple-800',
            'blog': 'bg-yellow-100 text-yellow-800',
            'websearch': 'bg-red-100 text-red-800',
            'db': 'bg-gray-100 text-gray-800'
        };

        // 통계 로드
        fetch('/api/history/stats')
            .then(r => r.json())
            .then(data => {
                document.getElementById('stats').innerHTML = data.stats.map(s => {
                    const colorClass = toolColors[s.tool] || 'bg-gray-100 text-gray-800';
                    const lastUsed = s.last_used ? new Date(s.last_used).toLocaleString('ko-KR') : 'N/A';
                    return `
                        <div class="bg-white p-6 rounded-lg shadow-md hover:shadow-lg transition-shadow">
                            <div class="flex items-center justify-between mb-4">
                                <span class="inline-block px-3 py-1 rounded-full text-sm font-semibold ${colorClass}">
                                    ${s.tool || 'unknown'}
                                </span>
                            </div>
                            <div class="text-3xl font-bold text-gray-800 mb-2">${s.count}회</div>
                            <div class="text-sm text-gray-600 mb-1">평균 품질: ${s.avg_score}점</div>
                            <div class="text-xs text-gray-500">마지막: ${lastUsed}</div>
                        </div>
                    `;
                }).join('');
            })
            .catch(err => {
                document.getElementById('stats').innerHTML = `
                    <div class="col-span-full bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
                        ⚠️ 통계 로드 실패: ${err.message}
                    </div>
                `;
            });

        // 대화 기록 로드
        fetch('/api/history?limit=50')
            .then(r => r.json())
            .then(data => {
                if (data.history.length === 0) {
                    document.getElementById('history').innerHTML = `
                        <div class="bg-white p-8 rounded-lg shadow-md text-center text-gray-500">
                            아직 대화 기록이 없습니다.
                        </div>
                    `;
                    return;
                }

                document.getElementById('history').innerHTML = data.history.map(h => {
                    const isUser = h.role === 'user';
                    const bgColor = isUser ? 'bg-blue-50 border-blue-200' : 'bg-white';
                    const icon = isUser ? '👤' : '🤖';
                    const roleText = isUser ? '사용자' : 'AI 어시스턴트';
                    const toolColorClass = toolColors[h.tool] || 'bg-gray-100 text-gray-800';
                    const timestamp = new Date(h.created_at).toLocaleString('ko-KR');

                    // 내용 미리보기 (200자 제한)
                    const preview = h.content.length > 200
                        ? h.content.substring(0, 200) + '...'
                        : h.content;

                    return `
                        <div class="bg-white rounded-lg shadow-md overflow-hidden border-l-4 ${isUser ? 'border-blue-500' : 'border-green-500'}">
                            <div class="p-6">
                                <div class="flex items-center justify-between mb-3">
                                    <div class="flex items-center space-x-2">
                                        <span class="text-2xl">${icon}</span>
                                        <span class="font-bold text-gray-800">${roleText}</span>
                                    </div>
                                    <div class="flex items-center space-x-2 text-sm text-gray-500">
                                        ${h.tool ? `<span class="px-2 py-1 rounded-full ${toolColorClass} font-semibold">${h.tool}</span>` : ''}
                                        ${h.score ? `<span class="px-2 py-1 rounded-full bg-gray-100 text-gray-700">📊 ${h.score}점</span>` : ''}
                                        <span>🕐 ${timestamp}</span>
                                    </div>
                                </div>
                                <div class="text-gray-700 whitespace-pre-wrap leading-relaxed">${preview}</div>
                            </div>
                        </div>
                    `;
                }).join('');
            })
            .catch(err => {
                document.getElementById('history').innerHTML = `
                    <div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
                        ⚠️ 대화 기록 로드 실패: ${err.message}
                    </div>
                `;
            });
    </script>
</body>
</html>
    """


# ─────────────────────────────
# 🤖 LangGraph Multi-Agent 엔드포인트
# ─────────────────────────────
@router.post("/ask-multi")
async def ask_law11_multi_agent(request: QueryRequest):
    """LangGraph Multi-Agent 시스템을 활용한 질문 응답 (메트릭 수집 포함)"""
    user_id = "law11_user"
    logger.info(f"🤖 [Multi-Agent] 요청 수신: {request.question}")

    try:
        full_answer_parts: List[str] = []

        async def event_stream():
            """Multi-Agent 실행 및 스트리밍.

            ⚠️ StreamingResponse(event_stream(), ...)는 이 제너레이터를 즉시
            실행하지 않는다 (실제 응답 전송 시점에 lazy하게 순회됨) — 그래서
            메트릭(duration, selected_agent)은 반드시 여기 안에서, 실제 작업이
            끝난 뒤에 기록해야 한다. 바깥(StreamingResponse 생성 직후)에서
            기록하면 duration은 항상 ~0초, selected_agent는 항상 "unknown"으로
            찍힌다 (실측 확인).
            """
            start_time = time.time()
            selected_agent = "unknown"
            try:
                # Multi-Agent 실행
                final_state = await run_multi_agent(user_id, request.question)

                # 답변을 chunk로 나눠서 스트리밍
                answer = final_state.get("final_answer", "")

                # Agent 정보 전송
                selected_tool = final_state.get("selected_tool", "unknown")
                selected_agent = selected_tool

                # Agent 사용 메트릭 기록
                metrics_collector.record_agent_usage(selected_agent)

                status_msg = f"🤖 [{selected_tool}] 처리 완료"
                yield f"data: {json.dumps({'event': 'status', 'payload': status_msg})}\n\n"

                # 답변을 chunk로 나눠서 전송 (20자씩)
                chunk_size = 20
                for i in range(0, len(answer), chunk_size):
                    chunk_text = answer[i:i+chunk_size]
                    full_answer_parts.append(chunk_text)
                    yield f"data: {json.dumps({'event': 'text', 'payload': chunk_text})}\n\n"
                    await asyncio.sleep(0.01)  # 자연스러운 스트리밍

                # DB 저장
                full_answer = "".join(full_answer_parts)
                tool_name = final_state.get("selected_tool", "").split("_")[0]

                try:
                    await save_chat_history(user_id, request.question, full_answer, tool_name)
                    yield f"data: {json.dumps({'event': 'status', 'payload': '✅ Multi-Agent 처리 완료'})}\n\n"
                except Exception as e:
                    logger.error(f"⚠️ [DB 저장 실패] {e}")
                    # ⚠️ type="warning"은 Literal에도 없고 프론트엔드 스위치문에도
                    # case가 없어 조용히 버려진다 (오늘 이미 확인한 버그와 동일
                    # 원인) — 이미 처리되는 "error"를 재사용.
                    yield f"data: {ToolChunk(type='error', payload='⚠️ DB 저장 실패').to_json()}\n\n"

                metrics_collector.record_response_time("/ask-multi", selected_agent, time.time() - start_time)
                metrics_collector.record_request("/ask-multi", selected_agent, "success")

            except Exception as e:
                metrics_collector.record_response_time("/ask-multi", selected_agent, time.time() - start_time)
                metrics_collector.record_error("/ask-multi", type(e).__name__)
                metrics_collector.record_request("/ask-multi", selected_agent, "error")
                logger.error(f"❌ [Multi-Agent 에러] {e}", exc_info=True)
                yield f"data: {ToolChunk(type='error', payload=f'❌ Multi-Agent 처리 중 오류: {str(e)}').to_json()}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"❌ [Multi-Agent 에러] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────
# 📊 MLOps 모니터링 엔드포인트
# ─────────────────────────────
@router.get("/metrics")
async def get_metrics():
    """Prometheus 메트릭 엔드포인트"""
    return Response(content=get_prometheus_metrics(), media_type=CONTENT_TYPE_LATEST)


@router.get("/metrics/summary")
async def get_metrics_summary():
    """메트릭 요약 정보 (사람이 읽을 수 있는 형태)"""
    summary = metrics_collector.get_summary()

    return {
        "status": "ok",
        "service": "Law11 Multi-Agent System",
        "metrics": summary,
        "endpoints": {
            "prometheus_metrics": "/api/metrics",
            "summary": "/api/metrics/summary"
        }
    }


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """사용자 피드백 저장 (👍 = 1, 👎 = -1)"""
    if request.value not in (1, -1):
        raise HTTPException(status_code=400, detail="value must be 1 or -1")
    sql = text("""
        UPDATE chat_history SET feedback = :value
        WHERE id = :id AND role = 'assistant'
    """)
    try:
        async with async_engine.begin() as conn:
            await conn.execute(sql, {"value": request.value, "id": request.message_id})
        logger.info(f"👍 [피드백 저장] id={request.message_id} value={request.value}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"⚠️ [피드백 저장 실패] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "service": "Law11 Backend",
        "timestamp": time.time()
    }


# ─────────────────────────────
# 📋 세션 관리 API
# ─────────────────────────────
@router.get("/session/{session_id}")
async def get_session(session_id: str, limit: int = 50):
    """세션 대화 목록 조회"""
    sql = text("""
        SELECT id, role, content, metadata, score, created_at
        FROM chat_history
        WHERE session_id = :session_id
        ORDER BY created_at ASC
        LIMIT :limit
    """)
    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(sql, {"session_id": session_id, "limit": limit})
            rows = result.fetchall()
        history = [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "tool": row.metadata.get("tool") if row.metadata else None,
                "score": row.score,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
        return {"session_id": session_id, "total": len(history), "history": history}
    except Exception as e:
        logger.error(f"⚠️ [Session 조회 실패] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """세션 삭제"""
    sql = text("DELETE FROM chat_history WHERE session_id = :session_id")
    try:
        async with async_engine.begin() as conn:
            await conn.execute(sql, {"session_id": session_id})
        logger.info(f"🗑️ [Session 삭제] {session_id}")
    except Exception as e:
        logger.error(f"⚠️ [Session 삭제 실패] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────
# 법령 조문 조회 API
# ─────────────────────────────
@router.get("/law")
async def get_law_article(name: str, article: str):
    """법령명 + 조문번호로 특정 조문 조회"""
    if not name.strip() or not article.strip():
        raise HTTPException(status_code=422, detail="name과 article은 필수 값입니다")
    law_norm = normalize_law_name(name)
    article_norm = normalize_article(article)

    sql = text("""
        SELECT law_name, text, enforcement_date
        FROM law_chunks
        WHERE law_name_norm = :law AND article_number_norm = :article
        LIMIT 1
    """)
    try:
        async with async_engine.begin() as conn:
            result = await conn.execute(sql, {"law": law_norm, "article": article_norm})
            row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="조문을 찾을 수 없습니다")
        return {
            "law_name": row.law_name,
            "articles": [{
                "law_name": row.law_name,
                "article_number": article_norm,
                "law_name_norm": law_norm,
                "article_number_norm": article_norm,
                "text": row.text,
                "enforcement_date": str(row.enforcement_date) if row.enforcement_date else None,
            }],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[법령 조회 실패] {e}")
        raise HTTPException(status_code=500, detail=str(e))

