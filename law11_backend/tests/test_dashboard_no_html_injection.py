"""/api/dashboard가 서버 데이터를 innerHTML에 날것으로 넣지 않는다 (#91).

예전 페이지는 /api/history의 `content`(사용자 질문·AI 답변 원문)를 템플릿 문자열로
innerHTML에 꽂았다 — 질문에 `<img src=x onerror=…>`를 쓰면 대시보드를 여는 사람의
브라우저에서 실행되는 저장형 XSS. 본문 목록은 뺐고(#81로 이미 비어 있었다), 남은
통계 필드는 전부 esc()를 거친다. 여기서는 그 HTML 문자열 자체를 검사한다.
"""
import re

import pytest

from app.api.routes import dashboard


@pytest.mark.asyncio
async def test_dashboard_has_no_raw_interpolation_of_server_data():
    html = await dashboard()
    assert "/api/history?" not in html and "h.content" not in html, "대화 본문 목록이 다시 들어왔다"
    # innerHTML 템플릿 안의 ${…} 중 esc( 를 거치지 않은 서버 필드가 없어야 한다
    raw = [m for m in re.findall(r"\$\{([^}]*)\}", html)
           if not m.startswith("esc(") and re.search(r"\b(s|h|err|data)\.", m)]
    assert not raw, f"esc() 없이 innerHTML에 들어가는 서버 필드: {raw}"
    assert "const esc = " in html
