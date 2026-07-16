import type { InterviewPublicEvent } from "../../types/interview";

interface AgentProgressProps {
  events: InterviewPublicEvent[];
  completed: boolean;
}

export function AgentProgress({ events, completed }: AgentProgressProps) {
  const visibleEvents = events.filter((event) => event.event_type !== "heartbeat");
  const current = visibleEvents.at(-1);
  if (!current) {
    return completed ? null : (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <span aria-hidden="true" className="size-2 animate-pulse rounded-full bg-neutral-600" />
        正在生成最终回答
      </div>
    );
  }
  if (completed) {
    return (
      <details className="mt-4 text-xs text-slate-500">
        <summary className="cursor-pointer select-none font-medium">查看执行状态</summary>
        <ol className="mt-2 space-y-1 border-l border-slate-200 pl-3">
          {visibleEvents.map((event, index) => (
            <li key={`${event.event_type}-${index}`}>{event.public_message}</li>
          ))}
        </ol>
      </details>
    );
  }
  return (
    <div aria-live="polite" className="space-y-2">
      <div className="flex items-center gap-2 text-sm text-slate-600">
        <span aria-hidden="true" className="size-2 animate-pulse rounded-full bg-neutral-600" />
        {current.public_message}
      </div>
      <div
        aria-label={`回答进度 ${current.progress}%`}
        className="h-1 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
      >
        <div
          className="h-full rounded-full bg-neutral-800 transition-[width]"
          style={{ width: `${current.progress}%` }}
        />
      </div>
    </div>
  );
}
