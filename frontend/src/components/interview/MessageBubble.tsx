import type { ReactNode } from "react";

interface MessageBubbleProps {
  children: ReactNode;
  label: string;
  side: "left" | "right";
}

export function MessageBubble({ children, label, side }: MessageBubbleProps) {
  if (side === "right") {
    return (
      <article
        aria-label={label}
        className="ml-auto max-w-[86%] rounded-3xl rounded-br-lg bg-neutral-200 px-4 py-3 text-sm leading-6 text-neutral-900 sm:max-w-[72%]"
        data-side="right"
      >
        {children}
      </article>
    );
  }

  return (
    <article
      aria-label={label}
      className="mr-auto flex w-full max-w-3xl gap-3"
      data-side="left"
    >
      <div className="mt-1 grid size-9 shrink-0 place-items-center rounded-2xl bg-neutral-950 text-xs font-bold text-white">
        AI
      </div>
      <div className="min-w-0 flex-1 rounded-3xl border border-black/5 bg-white p-4 shadow-[0_10px_30px_rgba(0,0,0,0.035)] sm:p-5">
        {children}
      </div>
    </article>
  );
}
