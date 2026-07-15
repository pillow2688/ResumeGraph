export interface InterviewAskRequest {
  question: string;
  project_ids?: string[];
}

export interface InterviewCitation {
  citation_handle: string;
  document_scope: "profile" | "project";
  project_id: string | null;
  project_name: string | null;
  document_title: string;
  version_number: number;
  heading_path: string[];
}

export interface InterviewAskResponse {
  status: "answered" | "insufficient_evidence";
  answer: string;
  citations: InterviewCitation[];
  remaining_requests: number;
}
