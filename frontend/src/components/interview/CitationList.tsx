import type { InterviewPublicCitation } from "../../types/interview";
import { citationTypeLabels } from "./citationLabels";

interface CitationListProps {
  citations: InterviewPublicCitation[];
  onOpen: (citation: InterviewPublicCitation) => void;
}

export function CitationList({ citations, onOpen }: CitationListProps) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-5 border-t border-slate-100 pt-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">引用资料</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {citations.map((citation, index) => (
          <button
            aria-label={`引用 ${index + 1}：${citation.document_title}`}
            className="inline-flex max-w-full items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-left text-xs text-slate-700 hover:border-cyan-300 hover:bg-cyan-50"
            key={citation.citation_handle}
            onClick={() => onOpen(citation)}
            type="button"
          >
            <span className="font-bold text-cyan-800">[{index + 1}]</span>
            <span className="font-semibold">
              {citationTypeLabels[citation.knowledge_type]}
            </span>
            <span className="hidden max-w-52 truncate text-slate-500 sm:inline">
              {citation.project_name ? `${citation.project_name} / ` : ""}
              {citation.document_title}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
