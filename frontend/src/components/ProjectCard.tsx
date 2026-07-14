import { Link } from "react-router-dom";

import type { Project } from "../types/project";

interface ProjectCardProps {
  project: Project;
  onDelete: (project: Project) => void;
  onEdit: (project: Project) => void;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "更新时间未知";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function ProjectCard({ project, onDelete, onEdit }: ProjectCardProps) {
  return (
    <article
      className="group flex min-h-64 flex-col rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
      data-testid={`project-${project.id}`}
    >
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="grid size-11 shrink-0 place-items-center rounded-xl bg-cyan-50 text-lg font-semibold text-cyan-800">
          {project.name.slice(0, 1).toUpperCase()}
        </div>
        <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
          Project
        </span>
      </div>

      <h2 className="text-xl font-semibold tracking-tight text-slate-950">{project.name}</h2>
      <p className="mt-2 line-clamp-3 flex-1 text-sm leading-6 text-slate-600">
        {project.description || "暂无项目描述。"}
      </p>

      <div className="mt-6 flex items-center justify-between border-t border-slate-100 pt-4">
        <p className="text-xs text-slate-500">更新于 {formatDate(project.updated_at)}</p>
        <div className="flex items-center gap-2">
          <Link
            className="rounded-lg px-3 py-2 text-sm font-medium text-cyan-800 transition hover:bg-cyan-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-700"
            to={`/admin/projects/${project.id}/documents`}
          >
            知识文档
          </Link>
          <button
            className="rounded-lg px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700"
            onClick={() => onEdit(project)}
            type="button"
          >
            编辑
          </button>
          <button
            className="rounded-lg px-3 py-2 text-sm font-medium text-rose-700 transition hover:bg-rose-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-700"
            onClick={() => onDelete(project)}
            type="button"
          >
            删除
          </button>
        </div>
      </div>
    </article>
  );
}
