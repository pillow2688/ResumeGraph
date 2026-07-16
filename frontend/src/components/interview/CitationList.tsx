import type { InterviewPublicCitation } from "../../types/interview";
import { CitationCard } from "./CitationCard";

interface CitationListProps {
  citations: InterviewPublicCitation[];
  onOpen: (citation: InterviewPublicCitation) => void;
}

export function CitationList({ citations, onOpen }: CitationListProps) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-5 border-t border-neutral-100 pt-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-neutral-400">引用资料</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {citations.map((citation, index) => (
          <CitationCard
            citation={citation}
            index={index}
            key={citation.citation_handle}
            onOpen={onOpen}
          />
        ))}
      </div>
    </div>
  );
}
