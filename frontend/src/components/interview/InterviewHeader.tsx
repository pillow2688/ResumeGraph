interface InterviewHeaderProps {
  projectNames: string[];
  remainingRequests: number;
  conversationReady: boolean;
  onMenu: () => void;
  onNewConversation: () => void;
}

export function InterviewHeader({
  projectNames,
  remainingRequests,
  conversationReady,
  onMenu,
  onNewConversation,
}: InterviewHeaderProps) {
  return (
    <header className="z-20 shrink-0 border-b border-neutral-200 bg-white/90 px-4 py-3 backdrop-blur sm:px-6">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <button
            aria-label="打开会话侧栏"
            className="grid size-10 shrink-0 place-items-center rounded-xl border border-slate-200 bg-white lg:hidden"
            onClick={onMenu}
            type="button"
          >
            ☰
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-base font-semibold sm:text-lg">AI 面试助手</h1>
              <span className="hidden rounded-full border border-neutral-200 bg-neutral-100 px-2 py-0.5 text-[11px] font-semibold text-neutral-700 sm:inline">
                {conversationReady ? "对话可用" : "正在连接"}
              </span>
            </div>
            <p className="truncate text-xs text-slate-500">
              当前范围：{projectNames.length > 0 ? projectNames.join("、") : "Profile 与 Technical"}
              <span className="mx-2">·</span>剩余 {remainingRequests} 次
            </p>
          </div>
        </div>
        <button
          className="hidden rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold hover:bg-slate-50 sm:block"
          disabled={!conversationReady}
          onClick={onNewConversation}
          type="button"
        >
          新建对话
        </button>
      </div>
      <p className="mx-auto mt-2 max-w-5xl text-xs leading-5 text-slate-500">
        回答基于候选人授权发布的简历和项目资料生成，正式结论以本人面试回答为准。
      </p>
    </header>
  );
}
