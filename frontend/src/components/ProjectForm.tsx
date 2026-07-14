import { useState, type FormEvent } from "react";

import type { Project, ProjectCreateRequest } from "../types/project";

interface ProjectFormProps {
  initialProject?: Project;
  isSaving: boolean;
  onCancel: () => void;
  onSubmit: (payload: ProjectCreateRequest) => Promise<void>;
}

export function ProjectForm({
  initialProject,
  isSaving,
  onCancel,
  onSubmit,
}: ProjectFormProps) {
  const [name, setName] = useState(initialProject?.name ?? "");
  const [description, setDescription] = useState(initialProject?.description ?? "");

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      return;
    }

    await onSubmit({
      name: normalizedName,
      description: description.trim(),
    });
  }

  return (
    <div
      aria-labelledby="project-form-title"
      aria-modal="true"
      className="fixed inset-0 z-40 grid place-items-center bg-slate-950/45 p-4 backdrop-blur-sm"
      role="dialog"
    >
      <form
        className="w-full max-w-xl rounded-3xl bg-white p-6 shadow-2xl sm:p-8"
        onSubmit={handleSubmit}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-cyan-700">
              {initialProject ? "编辑项目" : "新建项目"}
            </p>
            <h2
              className="mt-1 text-2xl font-semibold tracking-tight text-slate-950"
              id="project-form-title"
            >
              {initialProject ? "更新项目信息" : "创建一个项目"}
            </h2>
          </div>
          <button
            aria-label="关闭项目表单"
            className="grid size-9 place-items-center rounded-full text-xl text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
            disabled={isSaving}
            onClick={onCancel}
            type="button"
          >
            ×
          </button>
        </div>

        <div className="mt-7 space-y-5">
          <label className="block text-sm font-medium text-slate-800">
            项目名称
            <input
              autoFocus
              className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-base outline-none transition placeholder:text-slate-400 focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
              maxLength={200}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：ResumeGraph"
              required
              value={name}
            />
          </label>

          <label className="block text-sm font-medium text-slate-800">
            项目描述
            <textarea
              className="mt-2 min-h-36 w-full resize-y rounded-xl border border-slate-300 bg-white px-4 py-3 text-base leading-6 outline-none transition placeholder:text-slate-400 focus:border-cyan-700 focus:ring-4 focus:ring-cyan-100"
              maxLength={5000}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="简要说明项目目标、职责或技术重点"
              value={description}
            />
          </label>
        </div>

        <div className="mt-7 flex justify-end gap-3">
          <button
            className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isSaving}
            onClick={onCancel}
            type="button"
          >
            取消
          </button>
          <button
            className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={isSaving || !name.trim()}
            type="submit"
          >
            {isSaving ? "正在保存…" : initialProject ? "保存更改" : "保存项目"}
          </button>
        </div>
      </form>
    </div>
  );
}
