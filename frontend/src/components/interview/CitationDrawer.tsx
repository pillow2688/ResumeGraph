import type { InterviewPublicCitation } from "../../types/interview";
import { citationTypeLabels } from "./citationLabels";

interface CitationDrawerProps {
  citation: InterviewPublicCitation | null;
  onClose: () => void;
}

export function CitationDrawer({ citation, onClose }: CitationDrawerProps) {
  if (!citation) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end bg-slate-950/25 sm:items-stretch">
      <button
        aria-label="关闭引用详情"
        className="absolute inset-0 cursor-default"
        onClick={onClose}
        type="button"
      />
      <aside
        aria-label="引用详情"
        aria-modal="true"
        className="relative z-10 max-h-[82dvh] w-full overflow-y-auto rounded-t-3xl bg-white p-6 shadow-2xl sm:h-full sm:max-h-none sm:max-w-md sm:rounded-none sm:border-l sm:border-slate-200 sm:p-8"
        role="dialog"
      >
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-neutral-600">
              {citationTypeLabels[citation.knowledge_type]}
            </p>
            <h2 className="mt-1 text-xl font-semibold">引用详情</h2>
          </div>
          <button
            aria-label="关闭引用"
            className="grid size-10 place-items-center rounded-full border border-slate-200 text-xl hover:bg-slate-50"
            onClick={onClose}
            type="button"
          >
            ×
          </button>
        </div>
        <dl className="mt-7 space-y-5 text-sm">
          {citation.project_name ? (
            <div>
              <dt className="text-xs font-semibold text-slate-500">项目</dt>
              <dd className="mt-1 font-medium">{citation.project_name}</dd>
            </div>
          ) : null}
          <div>
            <dt className="text-xs font-semibold text-slate-500">文档</dt>
            <dd className="mt-1 font-medium">{citation.document_title}</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold text-slate-500">版本与位置</dt>
            <dd className="mt-1">
              v{citation.version_number}
              {citation.heading_path.length > 0
                ? ` · ${citation.heading_path.join(" / ")}`
                : ""}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold text-slate-500">允许展示的摘要</dt>
            <dd className="mt-2 rounded-xl bg-slate-50 p-4 leading-6 text-slate-700">
              {citation.excerpt}
            </dd>
          </div>
        </dl>
      </aside>
    </div>
  );
}
