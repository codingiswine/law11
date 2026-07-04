import React, { useEffect, useRef, useState } from "react";
import ChatMessage from "./ChatMessage";
import type { Message, LawReference, LawSource } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

interface ChatWindowProps {
  messages: Message[];
  activeQuestion: string | null;
  sessionId: string;
  onStreamStart?: () => void;
  onStreamComplete?: (answer: string, messageId?: number, sources?: LawSource[]) => void;
  onStreamError?: (message: string) => void;
  onFeedback?: (messageId: number, value: 1 | -1) => void;
  onLawClick?: (ref: LawReference) => void;
}

const ChatWindow: React.FC<ChatWindowProps> = ({
  messages,
  activeQuestion,
  sessionId,
  onStreamStart,
  onStreamComplete,
  onStreamError,
  onFeedback,
  onLawClick,
}) => {
  const [answer, setAnswer] = useState("");
  const [statusMessages, setStatusMessages] = useState<string[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const streamStartRef = useRef(onStreamStart);
  const streamCompleteRef = useRef(onStreamComplete);
  const streamErrorRef = useRef(onStreamError);

  useEffect(() => {
    streamStartRef.current = onStreamStart;
  }, [onStreamStart]);

  useEffect(() => {
    streamCompleteRef.current = onStreamComplete;
  }, [onStreamComplete]);

  useEffect(() => {
    streamErrorRef.current = onStreamError;
  }, [onStreamError]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, answer, statusMessages]);

  useEffect(() => {
    if (!activeQuestion) {
      return;
    }

    let isCancelled = false;
    const controller = new AbortController();
    const decoder = new TextDecoder("utf-8");
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    let buffer = "";
    let latestAnswer = "";
    let latestMessageId: number | undefined = undefined;
    let latestSources: LawSource[] = [];

    const pushStatus = (message: unknown, isError = false) => {
      const text =
        typeof message === "string"
          ? message
          : message !== undefined
          ? JSON.stringify(message)
          : "";
      if (!text) {
        return;
      }
      setStatusMessages((prev) => [
        ...prev,
        isError ? `❌ ${text}` : text,
      ]);
    };

    const handleLine = (rawLine: string) => {
      const line = rawLine.trim();
      if (!line) return;
    
      // ✅ "data:" 접두어 제거
      const cleanLine = line.startsWith("data:") ? line.replace(/^data:\s*/, "") : line;
    
      try {
        const data = JSON.parse(cleanLine);
        const eventType = data.event || data.type;
    
        switch (eventType) {
          case "text": {
            const payload = typeof data.payload === "string" ? data.payload : "";
            latestAnswer += payload;
            setAnswer((prev) => prev + payload);
            break;
          }
          case "status":
            pushStatus(data.payload);
            break;
          case "error":
            pushStatus(data.payload, true);
            break;
          case "saved": {
            const id = parseInt(data.payload, 10);
            if (!isNaN(id)) latestMessageId = id;
            break;
          }
          case "source": {
            const retrieved = data.payload?.retrieved_laws;
            if (Array.isArray(retrieved)) {
              latestSources = retrieved;
            }
            break;
          }
          default:
            break;
        }
      } catch (err) {
        console.error("Stream parse error:", err, line);
      }
    };
    

    const fetchStream = async () => {
      try {
        setAnswer("");
        setStatusMessages([]);
        setIsStreaming(true);
        streamStartRef.current?.();

        const response = await fetch(`${API_BASE_URL}/api/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: "linkcampus", question: activeQuestion, session_id: sessionId }),
          signal: controller.signal,
        });

        if (!response.ok) {
          pushStatus(`HTTP ${response.status}: ${response.statusText}`, true);
          return;
        }

        if (!response.body) {
          pushStatus("서버에서 빈 스트림이 반환되었습니다.", true);
          return;
        }

        reader = response.body.getReader();

        while (!isCancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            handleLine(line);
          }
        }

        if (buffer.trim()) {
          handleLine(buffer);
        }
      } catch (error) {
        if (isCancelled) return;
        const message =
          error instanceof Error ? error.message : "알 수 없는 오류가 발생했습니다.";
        pushStatus(message, true);
        streamErrorRef.current?.(message);
      } finally {
        if (!isCancelled) {
          setIsStreaming(false);
          streamCompleteRef.current?.(latestAnswer, latestMessageId, latestSources);
        }
      }
    };

    fetchStream();

    return () => {
      isCancelled = true;
      controller.abort();
      if (reader) {
        reader.cancel().catch(() => undefined);
      }
    };
  }, [activeQuestion]);

  useEffect(() => {
    if (!isStreaming && !activeQuestion) {
      setAnswer("");
      setStatusMessages([]);
    }
  }, [isStreaming, activeQuestion]);

  const shouldShowLiveAnswer = isStreaming || (!!answer && activeQuestion);

  return (
    <div className="space-y-4">
      {messages.map((msg, idx) => (
        <ChatMessage
          key={`${msg.role}-${idx}-${msg.content.slice(0, 20)}`}
          role={msg.role}
          content={msg.content}
          messageId={msg.messageId}
          feedback={msg.feedback}
          onFeedback={onFeedback}
          sources={msg.sources}
          onLawClick={onLawClick}
        />
      ))}

      {shouldShowLiveAnswer && (
        <div className="py-2 space-y-2">
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-gray-800">
            {answer || (
              <span className="text-gray-400 animate-pulse">답변을 생성 중입니다...</span>
            )}
          </div>
          <div className="space-y-0.5">
            {statusMessages.map((msg, i) => (
              <div
                key={`${msg}-${i}`}
                className={`text-xs ${
                  msg.startsWith("❌") ? "text-red-400" : "text-gray-400"
                }`}
              >
                {msg}
              </div>
            ))}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
};

export default ChatWindow;
