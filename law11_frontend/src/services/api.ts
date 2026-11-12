import type { LawContentResponse, Message, SessionSummary } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function submitFeedback(messageId: number, value: 1 | -1): Promise<void> {
  await fetch(`${API_BASE_URL}/api/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: messageId, value }),
  });
}

// article은 백엔드 /api/law의 필수 쿼리 파라미터다 (생략 시 422).
export async function getLawContent(name: string, article: string): Promise<LawContentResponse> {
  const params = new URLSearchParams({ name, article });
  const response = await fetch(`${API_BASE_URL}/api/law?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`법령 조회 실패: ${response.status}`);
  }
  return response.json();
}

// 이 브라우저가 만든/연 세션 ID 목록 (#81). 인증이 없어 "내 대화"의 유일한 근거다 —
// 서버는 여기 적힌 ID들만 돌려주고, 안 보내면 빈 목록을 준다.
const SESSIONS_KEY = "law11_session_ids";
const MAX_SESSIONS = 200;

export function ownSessionIds(): string[] {
  try {
    const ids = JSON.parse(localStorage.getItem(SESSIONS_KEY) || "[]");
    return Array.isArray(ids) ? ids.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function rememberSession(id: string): void {
  const ids = [id, ...ownSessionIds().filter(x => x !== id)].slice(0, MAX_SESSIONS);
  try { localStorage.setItem(SESSIONS_KEY, JSON.stringify(ids)); } catch { /* 저장 불가 환경이면 목록만 비어 보인다 */ }
}

export function forgetSession(id: string): void {
  try { localStorage.setItem(SESSIONS_KEY, JSON.stringify(ownSessionIds().filter(x => x !== id))); } catch { /* 위와 같음 */ }
}

export async function getHistory(): Promise<SessionSummary[]> {
  const ids = ownSessionIds();
  if (ids.length === 0) return [];
  try {
    const params = new URLSearchParams({ session_ids: ids.join(","), limit: "200" });
    const response = await fetch(`${API_BASE_URL}/api/history?${params.toString()}`);
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
  forgetSession(sessionId);
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
