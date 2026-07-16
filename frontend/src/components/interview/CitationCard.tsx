import type { InterviewPublicCitation } from "../../types/interview";
import { citationTypeLabels } from "./citationLabels";

interface CitationCardProps {
  citation: InterviewPublicCitation;
  index: number;
  onOpen: (citation: InterviewPublicCitation) => void;
}

export function CitationCard({ citation, index, onOpen }: CitationCardProps) {
  const source = citation.project_name ?? citation.document_title;
  const chunk =
    citation.heading_path.length > 0
      ? citation.heading_path.join(" / ")
      : citation.document_title;

  return (
    <button
      aria-label={`引用 ${index + 1}：${citation.document_title}`}
      className="group rounded-2xl border border-neutral-200 bg-neutral-50 p-4 text-left transition hover:border-neutral-400 hover:bg-white"
      onClick={() => onOpen(citation)}
      type="button"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-xs font-semibold text-neutral-900">
          <span aria-hidden="true">[{index + 1}]</span>
          <span>{citationTypeLabels[citation.knowledge_type]}</span>
        </span>
        <span className="text-xs text-neutral-400 transition group-hover:text-neutral-700">查看</span>
      </div>
      <dl className="mt-3 space-y-2 text-xs">
        <div>
          <dt className="font-semibold uppercase tracking-[0.14em] text-neutral-400">Source</dt>
          <dd className="mt-1 truncate font-medium text-neutral-800">{source}</dd>
        </div>
        <div>
          <dt className="font-semibold uppercase tracking-[0.14em] text-neutral-400">Chunk</dt>
          <dd className="mt-1 line-clamp-2 leading-5 text-neutral-600">{chunk}</dd>
        </div>
      </dl>
    </button>
  );
}
