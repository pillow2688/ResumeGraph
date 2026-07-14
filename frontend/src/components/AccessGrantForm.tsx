import { useState, type FormEvent } from "react";

import type { AccessGrantCreateRequest } from "../types/accessGrant";
import type { Project } from "../types/project";

interface AccessGrantFormProps {
  isSaving: boolean;
  onCancel: () => void;
  onSubmit: (payload: AccessGrantCreateRequest) => Promise<void>;
  projects: Project[];
}

function toLocalDateTimeInputValue(date: Date): string {
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return localDate.toISOString().slice(0, 16);
}

function defaultExpiry(): string {
  return toLocalDateTimeInputValue(new Date(Date.now() + 7 * 24 * 60 * 60 * 1000));
}

export function AccessGrantForm({
  isSaving,
  onCancel,
  onSubmit,
  projects,
}: AccessGrantFormProps) {
  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState(defaultExpiry);
  const [maxRequests, setMaxRequests] = useState(100);
  const [projectIds, setProjectIds] = useState<string[]>([]);

  function toggleProject(projectId: string): void {
    setProjectIds((current) =>
      current.includes(projectId)
        ? current.filter((id) => id !== projectId)
        : [...current, projectId],
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!name.trim() || projectIds.length === 0 || maxRequests < 1) {
      return;
    }

    await onSubmit({
      name: name.trim(),
      expires_at: new Date(expiresAt).toISOString(),
      max_requests: maxRequests,
      project_ids: projectIds,
    });
  }

  return (
    <div
      aria-labelledby="grant-form-title"
      aria-modal="true"
      className="fixed inset-0 z-40 grid place-items-center overflow-y-auto bg-slate-950/45 p-4 backdrop-blur-sm"
      role="dialog"
    >
      <form
        className="my-6 w-full max-w-2xl rounded-3xl bg-white p-6 shadow-2xl sm:p-8"
        onSubmit={handleSubmit}
      >
        <p className="text-sm font-semibold text-cyan-700">一次性访问授权</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight" id="grant-form-title">
          创建访问授权
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          选择面试官可以查看的项目，并设置有效期与请求上限。
        </p>

        <div className="mt-7 grid gap-5 sm:grid-cols-2">
          <label className="sm:col-span-2 block text-sm font-medium text-slate-800">
            授权名称
            <input
              autoFocus
              className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
              maxLength={200}
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </label>
          <label className="block text-sm font-medium text-slate-800">
            过期时间
            <input
              className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
              min={toLocalDateTimeInputValue(new Date())}
              onChange={(event) => setExpiresAt(event.target.value)}
              required
              type="datetime-local"
              value={expiresAt}
            />
          </label>
          <label className="block text-sm font-medium text-slate-800">
            最大请求次数
            <input
              className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
              max={1_000_000}
              min={1}
              onChange={(event) => setMaxRequests(event.target.valueAsNumber)}
              required
              type="number"
              value={maxRequests}
            />
          </label>
        </div>

        <fieldset className="mt-6">
          <legend className="text-sm font-medium text-slate-800">授权项目</legend>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {projects.map((project) => (
              <label
                className="flex items-start gap-3 rounded-xl border border-slate-200 p-4 text-sm hover:border-cyan-300"
                key={project.id}
              >
                <input
                  aria-label={project.name}
                  checked={projectIds.includes(project.id)}
                  className="mt-0.5 size-4 accent-cyan-700"
                  onChange={() => toggleProject(project.id)}
                  type="checkbox"
                />
                <span>
                  <span className="block font-semibold text-slate-900">{project.name}</span>
                  <span className="mt-1 line-clamp-2 block text-xs leading-5 text-slate-500">
                    {project.description || "暂无项目描述。"}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="mt-7 flex justify-end gap-3">
          <button
            className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            disabled={isSaving}
            onClick={onCancel}
            type="button"
          >
            取消
          </button>
          <button
            className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
            disabled={isSaving || !name.trim() || projectIds.length === 0 || maxRequests < 1}
            type="submit"
          >
            {isSaving ? "正在创建…" : "创建授权"}
          </button>
        </div>
      </form>
    </div>
  );
}
