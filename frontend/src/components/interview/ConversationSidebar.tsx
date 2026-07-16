import { Link } from "react-router-dom";

import type { RecruiterSession } from "../../types/accessGrant";

interface ConversationSidebarProps {
  session: RecruiterSession | null;
  conversationId: string | null;
  selectedProjectIds: string[];
  remainingRequests: number;
  open: boolean;
  disabled: boolean;
  onClose: () => void;
  onNewConversation: () => void;
  onProjectToggle: (projectId: string) => void;
  onLogout: () => void;
}

export function ConversationSidebar({
  session,
  conversationId,
  selectedProjectIds,
  remainingRequests,
  open,
  disabled,
  onClose,
  onNewConversation,
  onProjectToggle,
  onLogout,
}: ConversationSidebarProps) {
  return (
    <>
      {open ? (
        <button
          aria-label="关闭会话侧栏"
          className="fixed inset-0 z-30 bg-slate-950/30 lg:hidden"
          onClick={onClose}
          type="button"
        />
      ) : null}
      <aside
        aria-label="会话侧栏"
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-800 bg-slate-950 px-4 py-5 text-white transition-transform lg:static lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between gap-3 px-2">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-2xl bg-white text-sm font-black text-neutral-950">
              RG
            </div>
            <div>
              <p className="font-semibold">ResumeGraph</p>
              <p className="text-xs text-slate-400">Interview workspace</p>
            </div>
          </div>
          <button
            aria-label="关闭侧栏"
            className="grid size-9 place-items-center rounded-lg text-xl text-slate-300 hover:bg-white/10 lg:hidden"
            onClick={onClose}
            type="button"
          >
            ×
          </button>
        </div>

        <button
          className="mt-6 rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-left text-sm font-semibold hover:bg-white/10 disabled:opacity-50"
          disabled={disabled || !conversationId}
          onClick={onNewConversation}
          type="button"
        >
          ＋ 新建对话
        </button>

        <div className="mt-5 rounded-xl bg-white/5 p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            当前 Conversation
          </p>
          <p className="mt-2 text-sm font-medium">
            {conversationId ? "临时面试对话" : "正在创建对话…"}
          </p>
          {session ? (
            <p className="mt-1 truncate text-xs text-slate-300">{session.grant_name}</p>
          ) : null}
          <p className="mt-1 text-xs text-slate-400">Redis 临时保存，不提供长期历史</p>
        </div>

        <div className="mt-5 min-h-0 flex-1 overflow-y-auto px-1">
          <p className="px-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            当前授权项目
          </p>
          <div className="mt-3 space-y-2">
            {session?.allowed_projects.map((project) => (
              <label
                className="flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm hover:bg-white/5"
                key={project.id}
              >
                <input
                  aria-label={project.name}
                  checked={selectedProjectIds.includes(project.id)}
                  className="size-4 accent-white"
                  disabled={disabled}
                  onChange={() => onProjectToggle(project.id)}
                  type="checkbox"
                />
                <span className="min-w-0 truncate">{project.name}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="space-y-2 border-t border-white/10 pt-4">
          <p className="px-2 text-sm text-slate-300">剩余 {remainingRequests} 次</p>
          <Link
            className="block rounded-lg px-2 py-2 text-sm font-medium text-slate-300 hover:bg-white/5 hover:text-white"
            to="/portfolio"
          >
            返回 Portfolio
          </Link>
          <button
            className="w-full rounded-lg px-2 py-2 text-left text-sm font-medium text-slate-300 hover:bg-white/5 hover:text-white"
            disabled={disabled}
            onClick={onLogout}
            type="button"
          >
            退出访问
          </button>
        </div>
      </aside>
    </>
  );
}
