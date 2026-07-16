import { MessageBubble } from "./MessageBubble";

interface UserMessageBubbleProps {
  question: string;
}

export function UserMessageBubble({ question }: UserMessageBubbleProps) {
  return (
    <MessageBubble label="面试官消息" side="right">
      <p className="whitespace-pre-wrap">{question}</p>
      <span className="sr-only">面试官</span>
    </MessageBubble>
  );
}
