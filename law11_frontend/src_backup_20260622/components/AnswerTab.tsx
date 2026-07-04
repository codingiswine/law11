import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface AnswerTabProps {
  answer: string;
  isStreaming: boolean;
}

export const AnswerTab: React.FC<AnswerTabProps> = ({ answer, isStreaming }) => {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      {/* 헤더 */}
      <div className="flex items-center gap-2 mb-4">
        <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
        <h2 className="text-lg font-semibold text-gray-900">Answer</h2>
      </div>

      {/* 본문 */}
      <div className="prose prose-slate max-w-none text-gray-800 leading-relaxed">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            strong: ({ children }: { children: React.ReactNode }) => (
              <strong className="font-semibold text-gray-900">
                {children}
              </strong>
            ),
            a: ({
              href,
              children,
            }: {
              href?: string;
              children: React.ReactNode;
            }) => (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline"
              >
                {children}
              </a>
            ),
            li: ({ children }: { children: React.ReactNode }) => (
              <li className="list-disc ml-5">{children}</li>
            ),
            p: ({ children }: { children: React.ReactNode }) => (
              <p className="mb-2 last:mb-0">{children}</p>
            ),
          }}
        >
          {String(answer || "").replaceAll("\\n", "\n")}
        </ReactMarkdown>

        {isStreaming && (
          <span className="animate-pulse text-gray-400 ml-1">|</span>
        )}
      </div>
    </div>
  );
};
