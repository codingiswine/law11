import React, { useEffect, useState } from "react";
import { getHistory, deleteSession } from "../services/api";
import type { SessionSummary } from "../types";

interface SidebarProps {
  currentSessionId: string;
  onNewSession: () => void;
  onLoadSession: (sessionId: string) => void;
  refreshKey?: number;
}

const Sidebar: React.FC<SidebarProps> = ({ currentSessionId, onNewSession, onLoadSession, refreshKey }) => {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);

  useEffect(() => {
    getHistory().then(setSessions);
  }, [currentSessionId, refreshKey]);

  const handleDelete = async (sessionId: string) => {
    await deleteSession(sessionId);
    setSessions(prev => prev.filter(s => s.session_id !== sessionId));
    if (sessionId === currentSessionId) {
      onNewSession();
    }
  };

  return (
    <div style={{
      width: "240px",
      flexShrink: 0,
      height: "100vh",
      background: "#1a1a1a",
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* 로고 */}
      <div style={{ padding: "20px 16px 12px", borderBottom: "1px solid #2a2a2a" }}>
        <span style={{ fontWeight: 700, fontSize: "1rem", color: "#ffffff" }}>⚖️ Law11</span>
      </div>

      {/* 새 대화 버튼 */}
      <div style={{ padding: "12px" }}>
        <button
          onClick={onNewSession}
          style={{
            width: "100%",
            padding: "9px 12px",
            background: "#2a2a2a",
            border: "1px solid #3a3a3a",
            borderRadius: "8px",
            color: "#e5e5e5",
            fontSize: "0.85rem",
            fontWeight: 500,
            cursor: "pointer",
            textAlign: "left",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
          onMouseEnter={e => (e.currentTarget.style.background = "#333")}
          onMouseLeave={e => (e.currentTarget.style.background = "#2a2a2a")}
        >
          <span style={{ fontSize: "1rem" }}>＋</span>
          새 대화
        </button>
      </div>

      {/* 히스토리 */}
      <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 16px" }}>
        {sessions.length > 0 && (
          <div style={{ padding: "4px 8px 6px", fontSize: "0.7rem", color: "#666", fontWeight: 600, letterSpacing: "0.05em" }}>
            최근 대화
          </div>
        )}
        {sessions.map(s => (
          <div
            key={s.session_id}
            style={{
              display: "flex",
              alignItems: "center",
              background: s.session_id === currentSessionId ? "#2a2a2a" : "transparent",
              borderRadius: "6px",
              marginBottom: "2px",
            }}
            onMouseEnter={e => {
              if (s.session_id !== currentSessionId)
                e.currentTarget.style.background = "#242424";
              const del = e.currentTarget.querySelector<HTMLElement>("[data-del]");
              if (del) del.style.visibility = "visible";
            }}
            onMouseLeave={e => {
              if (s.session_id !== currentSessionId)
                e.currentTarget.style.background = "transparent";
              const del = e.currentTarget.querySelector<HTMLElement>("[data-del]");
              if (del) del.style.visibility = "hidden";
            }}
          >
            <button
              onClick={() => onLoadSession(s.session_id)}
              style={{
                flex: 1,
                minWidth: 0,
                padding: "8px 10px",
                background: "transparent",
                border: "none",
                color: s.session_id === currentSessionId ? "#ffffff" : "#9a9a9a",
                fontSize: "0.8rem",
                cursor: "pointer",
                textAlign: "left",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={s.title}
            >
              {s.title || "대화"}
            </button>
            <button
              data-del
              onClick={() => handleDelete(s.session_id)}
              style={{
                visibility: "hidden",
                flexShrink: 0,
                padding: "4px 8px",
                background: "transparent",
                border: "none",
                color: "#666",
                fontSize: "0.75rem",
                cursor: "pointer",
              }}
              title="대화 삭제"
            >
              ✕
            </button>
          </div>
        ))}
        {sessions.length === 0 && (
          <div style={{ padding: "16px 10px", color: "#555", fontSize: "0.78rem" }}>
            아직 대화 기록이 없습니다
          </div>
        )}
      </div>
    </div>
  );
};

export default Sidebar;
