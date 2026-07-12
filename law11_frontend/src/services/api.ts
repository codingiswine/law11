import type { QueryRequest, Source, LawContentResponse, Message, SessionSummary } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export class ApiService {
  static async askQuestion(request: QueryRequest): Promise<ReadableStream<Uint8Array>> {
    console.log('🌐 [API] 요청 URL:', `${API_BASE_URL}/api/ask`);
    console.log('📤 [API] 요청 데이터:', request);

    const response = await fetch(`${API_BASE_URL}/api/ask`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });

    console.log('📥 [API] 응답 상태:', response.status);
    console.log('📋 [API] 응답 헤더:', Object.fromEntries(response.headers.entries()));

    if (!response.ok) {
      const errorText = await response.text();
      console.error('❌ [API] 에러 응답:', errorText);
      throw new Error(`HTTP error! status: ${response.status}, body: ${errorText}`);
    }

    console.log('✅ [API] 스트림 반환');
    return response.body!;
  }

  static async submitFeedback(messageId: number, value: 1 | -1): Promise<void> {
    await fetch(`${API_BASE_URL}/api/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_id: messageId, value }),
    });
  }

  static async getLawContent(name: string, article: string = ""): Promise<LawContentResponse> {
    const params = new URLSearchParams({ name });
    if (article) params.append("article", article);
    const response = await fetch(`${API_BASE_URL}/api/law?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`법령 조회 실패: ${response.status}`);
    }
    return response.json();
  }

  static async getSources(query: string): Promise<Source[]> {
    const response = await fetch(`${API_BASE_URL}/api/sources?query=${encodeURIComponent(query)}`);

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return response.json();
  }

  static async getHistory(): Promise<SessionSummary[]> {
    try {
      const response = await fetch(`${API_BASE_URL}/api/history?user_id=law11_user&limit=200`);
      if (!response.ok) return [];
      const data = await response.json();
      const rows: any[] = data.history || [];

      // session_id 별로 그룹핑, 첫 user 메시지를 title로
      const sessionMap = new Map<string, { title: string; created_at: string }>();
      for (const row of rows) {
        const sid = row.session_id || "default";
        if (!sessionMap.has(sid) && row.role === "user") {
          sessionMap.set(sid, {
            title: row.content.slice(0, 60),
            created_at: row.created_at,
          });
        }
      }

      return Array.from(sessionMap.entries())
        .map(([session_id, v]) => ({ session_id, ...v }))
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    } catch {
      return [];
    }
  }

  static async getSession(sessionId: string): Promise<Message[]> {
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
}
