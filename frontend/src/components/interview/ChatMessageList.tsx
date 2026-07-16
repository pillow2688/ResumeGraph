import { useEffect, useRef, useState } from "react";

import type { InterviewPublicCitation } from "../../types/interview";
import { AssistantMessage } from "./AssistantMessage";
import type { InterviewChatTurn } from "./types";
import { UserMessageBubble } from "./UserMessageBubble";

interface ChatMessageListProps {
  turns: InterviewChatTurn[];
  onCitationOpen: (citation: InterviewPublicCitation) => void;
  onRetry: (question: string) => void;
}

export function ChatMessageList({
  turns,
  onCitationOpen,
  onRetry,
}: ChatMessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [followLatest, setFollowLatest] = useState(true);

  useEffect(() => {
    const container = containerRef.current;
    if (container && followLatest) {
      if (typeof container.scrollTo === "function") {
        container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
      } else {
        container.scrollTop = container.scrollHeight;
      }
    }
  }, [turns, followLatest]);

  function handleScroll(): void {
    const container = containerRef.current;
    if (!container) return;
    const distance = container.scrollHeight - container.scrollTop - container.clientHeight;
    setFollowLatest(distance < 120);
  }

  function scrollToBottom(): void {
    const container = containerRef.current;
    if (!container) return;
    setFollowLatest(true);
    if (typeof container.scrollTo === "function") {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    } else {
      container.scrollTop = container.scrollHeight;
    }
  }

  return (
    <div className="relative min-h-0 flex-1">
      <div
        aria-label="面试消息列表"
        className="h-full overflow-y-auto scroll-smooth px-4 py-6 sm:px-6"
        data-testid="chat-scroll-region"
        onScroll={handleScroll}
        ref={containerRef}
        role="log"
      >
        <div className="mx-auto max-w-5xl space-y-5">
          {turns.map((turn) => (
            <div className="space-y-4" key={turn.id}>
              <UserMessageBubble question={turn.question} />
              <AssistantMessage
                onCitationOpen={onCitationOpen}
                onRetry={onRetry}
                turn={turn}
              />
            </div>
          ))}
        </div>
      </div>
      {!followLatest ? (
        <button
          className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold shadow-lg"
          onClick={scrollToBottom}
          type="button"
        >
          ↓ 回到底部
        </button>
      ) : null}
    </div>
  );
}
