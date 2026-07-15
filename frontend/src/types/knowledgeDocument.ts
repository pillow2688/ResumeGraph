export type DocumentSourceType = "pasted_markdown" | "markdown_file";
export type DocumentVersionStatus = "draft" | "processing" | "ready_for_review";
export type IngestionJobStatus = "pending" | "processing" | "completed" | "failed";
export type IngestionJobStage = "reading" | "cleaning" | "chunking" | "saving";

export interface DocumentVersionSummary {
  id: string;
  document_id: string;
  version_number: number;
  source_type: DocumentSourceType;
  original_filename: string | null;
  status: DocumentVersionStatus;
  created_at: string;
  content_size_bytes: number;
}

export interface DocumentVersion extends DocumentVersionSummary {
  raw_content: string;
}

export interface KnowledgeDocumentSummary {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  version_count: number;
  latest_version: DocumentVersionSummary | null;
}

export interface KnowledgeDocument extends KnowledgeDocumentSummary {
  project: {
    id: string;
    name: string;
  };
}

export interface CreateDocumentRequest {
  title: string;
  content: string;
}

export interface CreateDocumentVersionRequest {
  content: string;
}

export interface UpdateDocumentTitleRequest {
  title: string;
}

export interface CreateIngestionJobResponse {
  job_id: string;
  status: IngestionJobStatus;
}

export interface IngestionJob {
  job_id: string;
  document_version_id: string;
  document_id: string;
  document_title: string;
  version_number: number;
  status: IngestionJobStatus;
  stage: IngestionJobStage;
  progress: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface DocumentChunk {
  id: string;
  document_version_id: string;
  chunk_index: number;
  heading_path: string[];
  content: string;
  content_hash: string;
  character_count: number;
  enabled: boolean;
  created_at: string;
}
