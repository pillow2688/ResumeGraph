interface UserMessageBubbleProps {
  question: string;
}

export function UserMessageBubble({ question }: UserMessageBubbleProps) {
  return (
    <article
      aria-label="面试官消息"
      className="ml-auto max-w-[82%] rounded-2xl rounded-br-md bg-slate-900 px-4 py-3 text-sm leading-6 text-white shadow-sm sm:max-w-[70%]"
      data-side="right"
    >
      <p className="whitespace-pre-wrap">{question}</p>
      <span className="sr-only">面试官</span>
    </article>
  );
}
