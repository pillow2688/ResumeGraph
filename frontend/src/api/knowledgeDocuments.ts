import type {
  CreateDocumentRequest,
  CreateDocumentVersionRequest,
  CreateIngestionJobResponse,
  DocumentChunk,
  DocumentVersion,
  DocumentVersionSummary,
  IngestionJob,
  KnowledgeDocument,
  KnowledgeDocumentSummary,
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
): Promise<KnowledgeDocument> {
  const body = new FormData();
  body.set("title", title);
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

export function getIngestionJob(jobId: string): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(`${adminPath}/jobs/${jobId}`);
}

export function listDocumentChunks(versionId: string): Promise<DocumentChunk[]> {
  return apiRequest<DocumentChunk[]>(
    `${adminPath}/document-versions/${versionId}/chunks`,
  );
}
