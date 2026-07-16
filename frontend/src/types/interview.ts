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

export type InterviewFinalStatus =
  | "answered"
  | "answered_with_boundary"
  | "partial_answer"
  | "insufficient_evidence"
  | "access_restricted";

export type InterviewKnowledgeType =
  | "profile_fact"
  | "project_fact"
  | "technical_knowledge"
  | "planned_solution";

export type InterviewDocumentScope = "profile" | "project" | "technical";
export type InterviewKnowledgeStatus =
  | "implemented"
  | "planned"
  | "general_knowledge";

export interface ConversationCreateResponse {
  conversation_id: string;
  expires_at: string;
  remaining_requests: number;
}

export interface ConversationAskRequest {
  request_id: string;
  question: string;
  project_ids?: string[];
}

export interface InterviewPublicCitation {
  citation_handle: string;
  knowledge_type: InterviewKnowledgeType;
  document_scope: InterviewDocumentScope;
  knowledge_status: InterviewKnowledgeStatus;
  project_id: string | null;
  project_name: string | null;
  document_title: string;
  version_number: number;
  heading_path: string[];
  excerpt: string;
}

export interface InterviewAgentTrace {
  agents_used: Array<
    | "profile_agent"
    | "project_agent"
    | "technical_agent"
    | "verification_agent"
  >;
  public_path: string[];
}

export interface ConversationContext {
  active_project_ids: string[];
  active_technical_topics: string[];
  turn_number: number;
}

export interface ConversationAskResponse {
  conversation_id: string;
  status: InterviewFinalStatus;
  answer: string;
  citations: InterviewPublicCitation[];
  agent_trace: InterviewAgentTrace;
  context: ConversationContext;
  remaining_requests: number;
}

export type InterviewPublicEventType =
  | "question_received"
  | "routing_started"
  | "routing_completed"
  | "profile_search_started"
  | "profile_search_completed"
  | "project_search_started"
  | "project_search_completed"
  | "technical_search_started"
  | "technical_search_completed"
  | "answer_drafting"
  | "verification_started"
  | "verification_completed"
  | "answer_repairing"
  | "answer_completed"
  | "request_failed"
  | "heartbeat";

export interface InterviewPublicEvent {
  event_type: InterviewPublicEventType;
  public_message: string;
  timestamp: string;
  progress: number;
  response?: ConversationAskResponse;
}
