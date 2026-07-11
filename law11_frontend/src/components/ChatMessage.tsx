import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { LawReference, LawSource } from "../types";

interface ChatMessageProps {
  role: string;
  content: string;
  messageId?: number;
  feedback?: 1 | -1 | null;
  onFeedback?: (messageId: number, value: 1 | -1) => void;
  sources?: LawSource[];
  onLawClick?: (ref: LawReference) => void;
}

interface MarkdownProps {
  children?: React.ReactNode;
}

interface LinkProps {
  href?: string;
  children?: React.ReactNode;
}

const ChatMessage: React.FC<ChatMessageProps> = ({ role, content, messageId, feedback, onFeedback, sources, onLawClick }) => {
  const isUser = role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end py-1">
        <div className="max-w-[75%] px-4 py-2.5 bg-gray-100 rounded-3xl text-sm text-gray-800 whitespace-pre-line break-words">
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="py-2">
      <div
        className="prose prose-sm max-w-none text-gray-800"
        style={{ wordBreak: "break-word", overflowWrap: "break-word" }}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: ({ children }: MarkdownProps) => (
              <p className="mb-3 leading-relaxed">{children}</p>
            ),
            strong: ({ children }: MarkdownProps) => (
              <strong className="font-semibold text-gray-900">{children}</strong>
            ),
            hr: () => <hr className="my-4 border-gray-200" />,
            a: ({ href, children }: LinkProps) => (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline"
                style={{ wordBreak: "break-all" }}
              >
                {children}
              </a>
            ),
            li: ({ children }: MarkdownProps) => (
              <li className="mb-1.5 leading-relaxed">{children}</li>
            ),
            h1: ({ children }: MarkdownProps) => (
              <h1 className="text-xl font-bold mb-3 text-gray-900">{children}</h1>
            ),
            h2: ({ children }: MarkdownProps) => (
              <h2 className="text-lg font-semibold mb-2 text-gray-900">{children}</h2>
            ),
            h3: ({ children }: MarkdownProps) => (
              <h3 className="text-base font-semibold mb-2 text-gray-800">{children}</h3>
            ),
            code: ({ children }: MarkdownProps) => (
              <code className="bg-gray-100 px-1.5 py-0.5 rounded text-sm font-mono" style={{ wordBreak: "break-all" }}>
                {children}
              </code>
            ),
            pre: ({ children }: MarkdownProps) => (
              <pre className="bg-gray-100 p-4 rounded-xl text-sm font-mono overflow-x-auto whitespace-pre-wrap">
                {children}
              </pre>
            ),
            blockquote: ({ children }: MarkdownProps) => (
              <blockquote className="border-l-4 border-gray-300 pl-4 my-3 text-gray-600 bg-gray-50 py-2 rounded-r">
                {children}
              </blockquote>
            ),
            ul: ({ children }: MarkdownProps) => (
              <ul className="list-disc ml-5 mb-3 space-y-1">{children}</ul>
            ),
            ol: ({ children }: MarkdownProps) => (
              <ol className="list-decimal ml-5 mb-3 space-y-1">{children}</ol>
            ),
          }}
        >
          {String(content || "").replaceAll("\\n", "\n")}
        </ReactMarkdown>
      </div>

      {sources && sources.length > 0 && (
        <div style={{ marginTop: "12px", display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
          <span style={{ fontSize: "0.75rem", color: "#9ca3af" }}>참고 법령:</span>
          {sources.map((source, i) => {
            const label = `${source.law_name} 제${source.article_number}조`;
            const scorePercent = source.score != null ? Math.round(source.score * 100) : null;
            return (
              <button
                key={i}
                onClick={() => onLawClick?.({ lawName: source.law_name, articleNumber: source.article_number, display: label })}
                style={{
                  fontSize: "0.75rem",
                  padding: "3px 10px",
                  borderRadius: "12px",
                  border: "1px solid #d1d5db",
                  background: "#f9fafb",
                  cursor: "pointer",
                  color: "#374151",
                  display: "flex",
                  alignItems: "center",
                  gap: "4px",
                }}
              >
                {label}
                {scorePercent != null && (
                  <span style={{
                    fontSize: "0.65rem",
                    background: scorePercent >= 70 ? "#dcfce7" : "#fef9c3",
                    color: scorePercent >= 70 ? "#15803d" : "#a16207",
                    borderRadius: "4px",
                    padding: "1px 4px",
                  }}>
                    {scorePercent}%
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {messageId && onFeedback && (
        <div className="flex gap-1 mt-2">
          <button
            onClick={() => onFeedback(messageId, 1)}
            title="도움이 됐어요"
            className={`text-base px-2 py-0.5 rounded-full transition-colors ${
              feedback === 1
                ? "bg-green-100 text-green-600"
                : "text-gray-300 hover:text-green-500"
            }`}
          >
            👍
          </button>
          <button
            onClick={() => onFeedback(messageId, -1)}
            title="도움이 안 됐어요"
            className={`text-base px-2 py-0.5 rounded-full transition-colors ${
              feedback === -1
                ? "bg-red-100 text-red-600"
                : "text-gray-300 hover:text-red-500"
            }`}
          >
            👎
          </button>
        </div>
      )}
    </div>
  );
};

export default ChatMessage;
