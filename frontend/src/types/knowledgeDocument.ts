export type DocumentSourceType = "pasted_markdown" | "markdown_file";
export type DocumentVersionStatus = "draft";

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
