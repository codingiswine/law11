import React, { useEffect, useState } from "react";
import { ApiService } from "../services/api";
import type { LawArticle } from "../types";

interface LawSidePanelProps {
  lawName: string;
  articleNumber: string;
  onClose: () => void;
}

const LawSidePanel: React.FC<LawSidePanelProps> = ({ lawName, articleNumber, onClose }) => {
  const [articles, setArticles] = useState<LawArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    ApiService.getLawContent(lawName, articleNumber)
      .then(data => setArticles(data.articles ?? []))
      .catch(async err => {
        if (err.message.includes("404") && articleNumber) {
          // 특정 조문 없음 → 법령 전체 상위 조문으로 재시도
          try {
            const data = await ApiService.getLawContent(lawName, "");
            setArticles(data.articles ?? []);
          } catch {
            setError("NOT_FOUND");
          }
        } else if (err.message.includes("404")) {
          setError("NOT_FOUND");
        } else {
          setError(err.message);
        }
      })
      .finally(() => setLoading(false));
  }, [lawName, articleNumber]);

  return (
    <div style={{
      width: "380px",
      flexShrink: 0,
      height: "100vh",
      background: "#fff",
      borderLeft: "1px solid #e5e7eb",
      display: "flex",
      flexDirection: "column",
    }}>
      <div style={{
        padding: "16px 20px", borderBottom: "1px solid #f3f4f6",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: "0.95rem", color: "#111827" }}>{lawName}</div>
          {articleNumber && (
            <div style={{ fontSize: "0.8rem", color: "#6b7280", marginTop: "2px" }}>
              제{articleNumber}조
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none", border: "none", cursor: "pointer",
            fontSize: "1.2rem", color: "#9ca3af", lineHeight: 1,
          }}
        >
          ✕
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "20px" }}>
        {loading && (
          <div style={{ color: "#9ca3af", fontSize: "0.875rem" }}>조문을 불러오는 중...</div>
        )}
        {error === "NOT_FOUND" && (
          <div style={{ padding: "4px 0" }}>
            <div style={{ fontSize: "0.875rem", color: "#6b7280", marginBottom: "16px" }}>
              데이터베이스에 등록되지 않은 법령입니다.
            </div>
            <a
              href={`https://www.law.go.kr/법령/${encodeURIComponent(lawName)}/${articleNumber ? `제${articleNumber}조` : ""}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "10px 16px",
                background: "#1a56db",
                color: "#fff",
                borderRadius: "8px",
                fontSize: "0.85rem",
                fontWeight: 500,
                textDecoration: "none",
              }}
            >
              ⚖️ 법령정보원에서 보기
            </a>
          </div>
        )}
        {error && error !== "NOT_FOUND" && (
          <div style={{ color: "#ef4444", fontSize: "0.875rem" }}>{error}</div>
        )}
        {!loading && !error && articles.length === 0 && (
          <div style={{ color: "#9ca3af", fontSize: "0.875rem" }}>조문을 찾을 수 없습니다.</div>
        )}
        {!loading && !error && articles.map((article, i) => (
          <div key={i} style={{ marginBottom: "24px" }}>
            <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#4b5563", marginBottom: "8px" }}>
              제{article.article_number}조
            </div>
            <div style={{ fontSize: "0.875rem", lineHeight: 1.7, color: "#374151", whiteSpace: "pre-wrap" }}>
              {article.text}
            </div>
            {article.enforcement_date && (
              <div style={{ fontSize: "0.75rem", color: "#9ca3af", marginTop: "8px" }}>
                시행일: {article.enforcement_date}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default LawSidePanel;
