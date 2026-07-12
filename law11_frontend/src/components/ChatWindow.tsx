import React, { useEffect, useRef, useState } from "react";
import ChatMessage from "./ChatMessage";
import type { Message, LawReference, LawSource } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// ✅ 웹 검색 폴백은 오래 걸리는데 마지막 상태 메시지가 그대로 멈춰 있어서
// "멈췄나?" 하는 느낌을 줌 — 답변이 오기 전까지 재밌는 문구를 랜덤 순환 표시.
const WEB_FALLBACK_TRIGGERS = ["Web 검색으로 보완", "Web fallback 실행"];
const FUNNY_SEARCH_MESSAGES = [
  "국가법령정보센터 서고 뒤엎는 중...",
  "구글 본사 뒤지는 중...",
  "판례 몰래 훔쳐보는 중...",
  "변호사 없이 혼자 법전 넘기는 중...",
  "인터넷 구석구석 탈탈 터는 중...",
  "관련 조문 붙잡고 심문하는 중...",
  "검색엔진들 닦달하는 중...",
  "클로드 본사 뒤지는 중...",
  "GPT 본사 뒤지는 중...",
];

function pickNextFunnyMessage(excludeIndex: number): number {
  if (FUNNY_SEARCH_MESSAGES.length <= 1) return 0;
  let next = Math.floor(Math.random() * FUNNY_SEARCH_MESSAGES.length);
  while (next === excludeIndex) {
    next = Math.floor(Math.random() * FUNNY_SEARCH_MESSAGES.length);
  }
  return next;
}

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
  const [displayedAnswer, setDisplayedAnswer] = useState("");
  const [statusMessages, setStatusMessages] = useState<string[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [funnyMessage, setFunnyMessage] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stopRef = useRef<(() => void) | null>(null);

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
  }, [messages, displayedAnswer, statusMessages]);

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

    // ✅ 질문 하나당 리빌 interval을 단 하나만 생성 — 완료 콜백도 같은 클로저에서
    // 발화하므로, 새 질문이 시작되면 cleanup에서 함께 취소되어 이전 질문의
    // 완료가 새 질문에 잘못 발화되는 경합이 원천적으로 불가능하다.
    let networkDone = false;
    let completed = false;
    let manuallyStopped = false;
    let revealedLength = 0;
    const revealTimer = setInterval(() => {
      if (!manuallyStopped && revealedLength < latestAnswer.length) {
        revealedLength = Math.min(revealedLength + 2, latestAnswer.length);
        setDisplayedAnswer(latestAnswer.slice(0, revealedLength));
      } else if (networkDone && !completed) {
        completed = true;
        clearInterval(revealTimer);
        streamCompleteRef.current?.(latestAnswer, latestMessageId, latestSources);
      }
    }, 15);

    // ✅ 생성 중지: 스트림을 끊고, 지금까지 받은 부분 답변을 그대로 확정한다.
    // networkDone을 세워두면 기존 완료 머신이 알아서 completion을 발화한다.
    stopRef.current = () => {
      if (manuallyStopped || completed) return;
      manuallyStopped = true;
      networkDone = true;
      // 화면에 보인 만큼만 확정 (멈춘 지점 = 저장되는 지점)
      latestAnswer = latestAnswer.slice(0, revealedLength);
      controller.abort();
      reader?.cancel().catch(() => undefined);
      setIsStreaming(false);
    };

    let funnyTimer: ReturnType<typeof setInterval> | null = null;
    let funnyIndex = -1;

    const stopFunnyRotation = () => {
      if (funnyTimer) {
        clearInterval(funnyTimer);
        funnyTimer = null;
      }
      setFunnyMessage(null);
    };

    const startFunnyRotation = () => {
      if (funnyTimer) return;
      funnyIndex = pickNextFunnyMessage(funnyIndex);
      setFunnyMessage(FUNNY_SEARCH_MESSAGES[funnyIndex]);
      funnyTimer = setInterval(() => {
        funnyIndex = pickNextFunnyMessage(funnyIndex);
        setFunnyMessage(FUNNY_SEARCH_MESSAGES[funnyIndex]);
      }, 2000);
    };

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
      if (!isError && WEB_FALLBACK_TRIGGERS.some((trigger) => text.includes(trigger))) {
        startFunnyRotation();
      }
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
            stopFunnyRotation();
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
        setDisplayedAnswer("");
        setStatusMessages([]);
        setFunnyMessage(null);
        setIsStreaming(true);
        streamStartRef.current?.();

        const response = await fetch(`${API_BASE_URL}/api/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: "law11_user", question: activeQuestion, session_id: sessionId }),
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
        // 수동 중지 시의 AbortError는 오류가 아님 — 완료 머신이 부분 답변을 확정한다
        if (isCancelled || manuallyStopped) return;
        const message =
          error instanceof Error ? error.message : "알 수 없는 오류가 발생했습니다.";
        pushStatus(message, true);
        streamErrorRef.current?.(message);
      } finally {
        if (!isCancelled) {
          setIsStreaming(false);
          networkDone = true;
        }
      }
    };

    fetchStream();

    return () => {
      isCancelled = true;
      stopRef.current = null;
      controller.abort();
      clearInterval(revealTimer);
      if (funnyTimer) clearInterval(funnyTimer);
      // ✅ 네트워크는 이미 끝났는데 타이핑 리빌이 안 끝난 채로 다음 질문이
      // 시작되면, 인터벌이 죽어 완료 콜백이 영영 안 불려 답변이 유실된다.
      // 리빌은 끊겨도 되지만 이미 받은 답변은 반드시 저장되어야 하므로 즉시 flush.
      if (networkDone && !completed) {
        completed = true;
        streamCompleteRef.current?.(latestAnswer, latestMessageId, latestSources);
      }
      if (reader) {
        reader.cancel().catch(() => undefined);
      }
    };
  }, [activeQuestion]);

  useEffect(() => {
    if (!isStreaming && !activeQuestion) {
      setDisplayedAnswer("");
      setStatusMessages([]);
      setFunnyMessage(null);
    }
  }, [isStreaming, activeQuestion]);

  const shouldShowLiveAnswer = isStreaming || (!!activeQuestion && displayedAnswer.length > 0);

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
            {displayedAnswer || (
              <span className="text-gray-400 animate-pulse">답변을 생성 중입니다...</span>
            )}
            {!!activeQuestion && displayedAnswer.length > 0 && (
              <span className="animate-pulse">▌</span>
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
            {funnyMessage && (
              <div className="text-xs text-gray-400 italic">{funnyMessage}</div>
            )}
          </div>
          {!!activeQuestion && (
            <button
              onClick={() => stopRef.current?.()}
              className="text-xs text-gray-500 border border-gray-300 rounded-full px-3 py-1 hover:bg-gray-100"
            >
              ⏹ 생성 중지
            </button>
          )}
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
};

export default ChatWindow;
