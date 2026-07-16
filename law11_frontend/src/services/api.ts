import type { LawContentResponse, Message, SessionSummary } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function submitFeedback(messageId: number, value: 1 | -1): Promise<void> {
  await fetch(`${API_BASE_URL}/api/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: messageId, value }),
  });
}

export async function getLawContent(name: string, article: string = ""): Promise<LawContentResponse> {
  const params = new URLSearchParams({ name });
  if (article) params.append("article", article);
  const response = await fetch(`${API_BASE_URL}/api/law?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`법령 조회 실패: ${response.status}`);
  }
  return response.json();
}

export async function getHistory(): Promise<SessionSummary[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/history?user_id=law11_user&limit=200`);
    if (!response.ok) return [];
    const data = await response.json();
    const rows: any[] = data.history || [];

    // session_id 별로 그룹핑 — 제목은 세션의 "첫" user 메시지,
    // 정렬은 마지막 활동 시각 기준 (최근에 이어간 대화가 위로)
    const sessionMap = new Map<string, { title: string; created_at: string }>();
    for (const row of [...rows].reverse()) { // API는 최신순 → 시간순으로 뒤집기
      const sid = row.session_id || "default";
      const existing = sessionMap.get(sid);
      if (!existing) {
        if (row.role === "user") {
          sessionMap.set(sid, {
            title: row.content.slice(0, 60),
            created_at: row.created_at,
          });
        }
      } else {
        existing.created_at = row.created_at;
      }
    }

    return Array.from(sessionMap.entries())
      .map(([session_id, v]) => ({ session_id, ...v }))
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  } catch {
    return [];
  }
}

export async function deleteSession(sessionId: string): Promise<void> {
  await fetch(`${API_BASE_URL}/api/session/${sessionId}`, { method: "DELETE" });
}

export async function getSession(sessionId: string): Promise<Message[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/session/${sessionId}`);
    if (!response.ok) return [];
    const data = await response.json();
    const rows: any[] = data.history || [];
    return rows.map((r: any) => ({
      role: r.role,
      content: r.content,
      messageId: r.id,
    }));
  } catch {
    return [];
  }
}
