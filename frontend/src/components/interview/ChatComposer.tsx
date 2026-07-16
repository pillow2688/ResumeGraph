import { useRef, type FormEvent, type KeyboardEvent } from "react";

interface ChatComposerProps {
  value: string;
  disabled: boolean;
  isSubmitting: boolean;
  projectNames: string[];
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
}

export function ChatComposer({
  value,
  disabled,
  isSubmitting,
  projectNames,
  onChange,
  onSend,
  onStop,
}: ChatComposerProps) {
  const composingRef = useRef(false);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSend();
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !composingRef.current &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      onSend();
    }
  }

  return (
    <div
      className="sticky bottom-0 z-20 shrink-0 border-t border-neutral-200 bg-white/95 px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur sm:px-6"
      data-testid="chat-composer"
    >
      <form
        className="mx-auto max-w-5xl rounded-3xl border border-neutral-300 bg-white p-2 shadow-[0_-8px_30px_rgba(0,0,0,0.035)] focus-within:border-neutral-500 focus-within:ring-4 focus-within:ring-neutral-100"
        onSubmit={submit}
      >
        <label className="sr-only" htmlFor="interview-question">
          面试问题
        </label>
        <textarea
          aria-label="面试问题"
          className="max-h-40 min-h-12 w-full resize-none overflow-y-auto border-0 bg-transparent px-3 py-2 text-[15px] leading-6 outline-none placeholder:text-slate-400"
          disabled={disabled || isSubmitting}
          id="interview-question"
          maxLength={1000}
          onChange={(event) => {
            onChange(event.target.value);
            event.target.style.height = "auto";
            event.target.style.height = `${Math.min(event.target.scrollHeight, 160)}px`;
          }}
          onCompositionEnd={() => {
            composingRef.current = false;
          }}
          onCompositionStart={() => {
            composingRef.current = true;
          }}
          onKeyDown={keyDown}
          placeholder="继续追问候选人的经历、项目或技术原理…"
          rows={1}
          value={value}
        />
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-2 pt-2">
          <div className="min-w-0 text-[11px] leading-5 text-slate-500">
            <p className="truncate">
              当前项目范围：{projectNames.length > 0 ? projectNames.join("、") : "Profile 与 Technical"}
            </p>
            <p>{value.length}/1000 · Enter 发送，Shift + Enter 换行</p>
          </div>
          {isSubmitting ? (
            <button
              className="rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800 hover:bg-rose-50"
              onClick={onStop}
              type="button"
            >
              停止生成
            </button>
          ) : (
            <button
              className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-40"
              disabled={disabled || !value.trim()}
              type="submit"
            >
              发送
            </button>
          )}
        </div>
      </form>
      <p className="mx-auto mt-2 max-w-5xl text-center text-[11px] text-slate-400">
        AI 回答可能存在遗漏，请结合引用资料判断。
      </p>
    </div>
  );
}
