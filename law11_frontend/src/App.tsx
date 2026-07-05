import { useCallback, useState } from "react";
import Sidebar from "./components/Sidebar";
import SearchBar from "./components/SearchBar";
import ChatWindow from "./components/ChatWindow";
import LawSidePanel from "./components/LawSidePanel";
import { ApiService } from "./services/api";
import type { Message, LawReference, LawSource } from "./types";

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [activeQuestion, setActiveQuestion] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string>(() => crypto.randomUUID());
  const [selectedLaw, setSelectedLaw] = useState<{ name: string; article: string } | null>(null);

  const handleSearch = (query: string) => {
    if (!query.trim()) return;
    setMessages(prev => [...prev, { role: "user", content: query }]);
    setActiveQuestion(query);
  };

  const handleNewSession = () => {
    setSessionId(crypto.randomUUID());
    setMessages([]);
    setActiveQuestion(null);
    setSelectedLaw(null);
  };

  const handleLoadSession = useCallback(async (sid: string) => {
    const loaded = await ApiService.getSession(sid);
    if (loaded.length > 0) {
      setMessages(loaded);
      setSessionId(sid);
      setActiveQuestion(null);
      setSelectedLaw(null);
    }
  }, []);

  const handleStreamComplete = useCallback((answer: string, messageId?: number, sources?: LawSource[]) => {
    if (answer.trim()) {
      setMessages(prev => [...prev, { role: "assistant", content: answer, messageId, sources: sources ?? [] }]);
    }
    setActiveQuestion(null);
  }, []);

  const handleLawClick = useCallback((ref: LawReference) => {
    setSelectedLaw(prev =>
      prev && prev.name === ref.lawName && prev.article === ref.articleNumber
        ? null
        : { name: ref.lawName, article: ref.articleNumber }
    );
  }, []);

  const handleFeedback = useCallback(async (messageId: number, value: 1 | -1) => {
    setMessages(prev =>
      prev.map(msg => msg.messageId === messageId ? { ...msg, feedback: value } : msg)
    );
    await ApiService.submitFeedback(messageId, value);
  }, []);

  const handleStreamError = useCallback((message: string) => {
    setMessages(prev => [
      ...prev,
      { role: "assistant", content: `죄송합니다. 오류가 발생했습니다: ${message}` },
    ]);
    setActiveQuestion(null);
  }, []);

  const hasStarted = messages.length > 0 || activeQuestion !== null;

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      {/* ── 왼쪽 사이드바 ── */}
      <Sidebar
        currentSessionId={sessionId}
        onNewSession={handleNewSession}
        onLoadSession={handleLoadSession}
      />

      {/* ── 가운데 채팅 영역 ── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "#f7f7f8", overflow: "hidden", minWidth: 0 }}>
        {!hasStarted ? (
          /* 랜딩 */
          <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "0 24px" }}>
            <h1 style={{ fontFamily: "'Outfit', sans-serif", fontSize: "2.2rem", fontWeight: 700, color: "#111827", marginBottom: "0.3rem" }}>
              Law11
            </h1>
            <p style={{ color: "#9ca3af", fontSize: "0.8rem", marginBottom: "0.4rem" }}>
              대한민국 헌법 11조: 모든 국민은 법 앞에 평등하다
            </p>
            <p style={{ color: "#6b7280", fontSize: "0.95rem", marginBottom: "2rem" }}>
              재난안전관리팀 전문 AI 어시스턴트
            </p>
            <div style={{ width: "100%", maxWidth: "640px" }}>
              <SearchBar onSearch={handleSearch} />
            </div>
            <div style={{ marginTop: "16px", display: "flex", gap: "8px", flexWrap: "wrap", justifyContent: "center" }}>
              {["안전관리자 선임 기준은?", "중대재해 처벌 범위가 어떻게 돼?", "비계 설치 안전 기준 알려줘"].map(q => (
                <button
                  key={q}
                  onClick={() => handleSearch(q)}
                  style={{
                    padding: "7px 14px",
                    borderRadius: "20px",
                    border: "1px solid #e5e7eb",
                    background: "#fff",
                    color: "#374151",
                    fontSize: "0.8rem",
                    cursor: "pointer",
                  }}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* 채팅 */
          <>
            {/* 헤더 */}
            <div style={{
              flexShrink: 0,
              padding: "14px 24px",
              borderBottom: "1px solid #ebebeb",
              background: "#f7f7f8",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}>
              <span style={{ fontFamily: "'Outfit', sans-serif", fontWeight: 600, fontSize: "0.95rem", color: "#374151" }}>
                Law11
              </span>
            </div>

            {/* 메시지 스크롤 */}
            <main style={{ flex: 1, overflowY: "auto", padding: "24px 24px 16px" }}>
              <div style={{ maxWidth: "700px", margin: "0 auto" }}>
                <ChatWindow
                  messages={messages}
                  activeQuestion={activeQuestion}
                  sessionId={sessionId}
                  onStreamComplete={handleStreamComplete}
                  onStreamError={handleStreamError}
                  onFeedback={handleFeedback}
                  onLawClick={handleLawClick}
                />
              </div>
            </main>

            {/* 하단 입력창 */}
            <div style={{ flexShrink: 0, padding: "12px 24px 24px", background: "#f7f7f8" }}>
              <div style={{ maxWidth: "700px", margin: "0 auto" }}>
                <SearchBar onSearch={handleSearch} />
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── 오른쪽 법령 패널 ── */}
      {selectedLaw && (
        <LawSidePanel
          lawName={selectedLaw.name}
          articleNumber={selectedLaw.article}
          onClose={() => setSelectedLaw(null)}
        />
      )}
    </div>
  );
}

export default App;
