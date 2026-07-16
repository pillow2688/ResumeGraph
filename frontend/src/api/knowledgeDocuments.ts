import type {
  CreateDocumentRequest,
  CreateDocumentVersionRequest,
  CreateIngestionJobResponse,
  DocumentChunk,
  DocumentVersion,
  DocumentVersionSummary,
  EmbeddingConfig,
  IngestionJob,
  KnowledgeDocument,
  KnowledgeDocumentSummary,
  PublicationState,
  ProjectKnowledgeStatus,
  TechnicalDocumentRequest,
  UpdateDocumentChunkRequest,
  UpdateDocumentTitleRequest,
} from "../types/knowledgeDocument";
import { apiFormRequest, apiRequest } from "./client";

const adminPath = "/api/v1/admin";

export function listProjectDocuments(
  projectId: string,
): Promise<KnowledgeDocumentSummary[]> {
  return apiRequest<KnowledgeDocumentSummary[]>(
    `${adminPath}/projects/${projectId}/documents`,
  );
}

export function listProfileDocuments(): Promise<KnowledgeDocumentSummary[]> {
  return apiRequest<KnowledgeDocumentSummary[]>(`${adminPath}/profile-documents`);
}

export function listTechnicalDocuments(): Promise<KnowledgeDocumentSummary[]> {
  return apiRequest<KnowledgeDocumentSummary[]>(
    `${adminPath}/technical-documents`,
  );
}

export function createPastedTechnicalDocument(
  payload: TechnicalDocumentRequest,
): Promise<KnowledgeDocument> {
  return apiRequest<KnowledgeDocument, TechnicalDocumentRequest>(
    `${adminPath}/technical-documents`,
    { method: "POST", body: payload },
  );
}

export function uploadTechnicalDocument(
  title: string,
  file: File,
): Promise<KnowledgeDocument> {
  const body = new FormData();
  body.set("title", title);
  body.set("knowledge_status", "general_knowledge");
  body.set("file", file);
  return apiFormRequest<KnowledgeDocument>(
    `${adminPath}/technical-documents/upload`,
    { method: "POST", body },
  );
}

export function createPastedProfileDocument(
  payload: CreateDocumentRequest,
): Promise<KnowledgeDocument> {
  return apiRequest<KnowledgeDocument, CreateDocumentRequest>(
    `${adminPath}/profile-documents`,
    { method: "POST", body: payload },
  );
}

export function uploadProfileDocument(
  title: string,
  file: File,
): Promise<KnowledgeDocument> {
  const body = new FormData();
  body.set("title", title);
  body.set("file", file);
  return apiFormRequest<KnowledgeDocument>(`${adminPath}/profile-documents/upload`, {
    method: "POST",
    body,
  });
}

export function createPastedDocument(
  projectId: string,
  payload: CreateDocumentRequest,
): Promise<KnowledgeDocument> {
  return apiRequest<KnowledgeDocument, CreateDocumentRequest>(
    `${adminPath}/projects/${projectId}/documents`,
    { method: "POST", body: payload },
  );
}

export function uploadDocument(
  projectId: string,
  title: string,
  file: File,
  knowledgeStatus: ProjectKnowledgeStatus = "implemented",
): Promise<KnowledgeDocument> {
  const body = new FormData();
  body.set("title", title);
  body.set("knowledge_status", knowledgeStatus);
  body.set("file", file);
  return apiFormRequest<KnowledgeDocument>(
    `${adminPath}/projects/${projectId}/documents/upload`,
    { method: "POST", body },
  );
}

export function getDocument(documentId: string): Promise<KnowledgeDocument> {
  return apiRequest<KnowledgeDocument>(`${adminPath}/documents/${documentId}`);
}

export function updateDocumentTitle(
  documentId: string,
  payload: UpdateDocumentTitleRequest,
): Promise<KnowledgeDocument> {
  return apiRequest<KnowledgeDocument, UpdateDocumentTitleRequest>(
    `${adminPath}/documents/${documentId}`,
    { method: "PATCH", body: payload },
  );
}

export function listDocumentVersions(
  documentId: string,
): Promise<DocumentVersionSummary[]> {
  return apiRequest<DocumentVersionSummary[]>(
    `${adminPath}/documents/${documentId}/versions`,
  );
}

export function createPastedVersion(
  documentId: string,
  payload: CreateDocumentVersionRequest,
): Promise<DocumentVersion> {
  return apiRequest<DocumentVersion, CreateDocumentVersionRequest>(
    `${adminPath}/documents/${documentId}/versions`,
    { method: "POST", body: payload },
  );
}

export function uploadVersion(
  documentId: string,
  file: File,
): Promise<DocumentVersion> {
  const body = new FormData();
  body.set("file", file);
  return apiFormRequest<DocumentVersion>(
    `${adminPath}/documents/${documentId}/versions/upload`,
    { method: "POST", body },
  );
}

export function getDocumentVersion(versionId: string): Promise<DocumentVersion> {
  return apiRequest<DocumentVersion>(`${adminPath}/document-versions/${versionId}`);
}

export function processDocumentVersion(
  versionId: string,
): Promise<CreateIngestionJobResponse> {
  return apiRequest<CreateIngestionJobResponse>(
    `${adminPath}/document-versions/${versionId}/process`,
    { method: "POST" },
  );
}

export function startKnowledgeIndexing(
  versionId: string,
): Promise<CreateIngestionJobResponse> {
  return apiRequest<CreateIngestionJobResponse>(
    `${adminPath}/document-versions/${versionId}/index`,
    { method: "POST" },
  );
}

export function getIngestionJob(jobId: string): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(`${adminPath}/jobs/${jobId}`);
}

export function listDocumentChunks(versionId: string): Promise<DocumentChunk[]> {
  return apiRequest<DocumentChunk[]>(
    `${adminPath}/document-versions/${versionId}/chunks`,
  );
}

export function updateDocumentChunk(
  chunkId: string,
  payload: UpdateDocumentChunkRequest,
): Promise<DocumentChunk> {
  return apiRequest<DocumentChunk, UpdateDocumentChunkRequest>(
    `${adminPath}/document-chunks/${chunkId}`,
    { method: "PATCH", body: payload },
  );
}

export function getEmbeddingConfig(): Promise<EmbeddingConfig> {
  return apiRequest<EmbeddingConfig>(`${adminPath}/embedding-config`);
}

export function publishDocumentVersion(versionId: string): Promise<PublicationState> {
  return apiRequest<PublicationState>(
    `${adminPath}/document-versions/${versionId}/publish`,
    { method: "POST" },
  );
}

export function unpublishDocument(documentId: string): Promise<PublicationState> {
  return apiRequest<PublicationState>(`${adminPath}/documents/${documentId}/publication`, {
    method: "DELETE",
  });
}

export function deleteDocumentVersion(versionId: string): Promise<void> {
  return apiRequest<void>(`${adminPath}/document-versions/${versionId}`, {
    method: "DELETE",
  });
}

export function permanentlyDeleteDocument(
  documentId: string,
  confirmationTitle: string,
): Promise<void> {
  return apiRequest<void, { confirmation_title: string }>(
    `${adminPath}/documents/${documentId}`,
    {
      method: "DELETE",
      body: { confirmation_title: confirmationTitle },
    },
  );
}
