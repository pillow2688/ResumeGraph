import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import {
  getEmbeddingConfig,
  listDocumentChunks,
  updateDocumentChunk,
} from "../api/knowledgeDocuments";
import { DocumentChunks } from "./DocumentChunks";

vi.mock("../api/knowledgeDocuments", () => ({
  getEmbeddingConfig: vi.fn(),
  listDocumentChunks: vi.fn(),
  updateDocumentChunk: vi.fn(),
}));

const versionId = "2aa4a8d2-67aa-4136-b02a-7422c1595743";
const listChunksMock = vi.mocked(listDocumentChunks);
const getEmbeddingConfigMock = vi.mocked(getEmbeddingConfig);
const updateChunkMock = vi.mocked(updateDocumentChunk);

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={[`/admin/document-versions/${versionId}/chunks`]}>
      <Routes>
        <Route
          path="/admin/document-versions/:versionId/chunks"
          element={<DocumentChunks />}
        />
        <Route path="/admin/login" element={<div>管理员登录</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DocumentChunks", () => {
  beforeEach(() => {
    listChunksMock.mockReset();
    getEmbeddingConfigMock.mockReset();
    updateChunkMock.mockReset();
    getEmbeddingConfigMock.mockResolvedValue({
      provider_name: "zhipu",
      base_url: "https://open.bigmodel.cn/api/paas/v4",
      model: "embedding-3",
      dimensions: 1024,
      send_dimensions: true,
      batch_size: 10,
      timeout_seconds: 30,
      max_retries: 2,
    });
  });

  it("shows stable chunk indexes, heading paths, and plain-text content", async () => {
    listChunksMock.mockResolvedValue([
      {
        id: "e4dd52c0-5063-42f6-b536-24b102f9756a",
        document_version_id: versionId,
        chunk_index: 0,
        heading_path: ["技术架构", "Worker"],
        content: "### Worker\n\n<script>alert('xss')</script>",
        content_hash: "a".repeat(64),
        character_count: 44,
        enabled: true,
        auto_indexable: false,
        quality_issues: [{ code: "pii_email", severity: "warning" }],
        extracted_metadata: {
          knowledge_type: "technical_decision",
          topics: ["RAG"],
          technologies: ["FastAPI"],
        },
        quality_checked_at: "2026-07-15T08:00:02Z",
        quality_model: "deepseek-chat",
        quality_reason: "Contains email PII.",
        created_at: "2026-07-15T08:00:02Z",
      },
    ]);
    renderPage();

    expect(await screen.findByRole("heading", { name: "Chunk 0" })).toBeInTheDocument();
    expect(screen.getByText("技术架构 / Worker")).toBeInTheDocument();
    const content = screen.getByTestId("chunk-content-0");
    expect(content).toHaveTextContent("<script>alert('xss')</script>");
    expect(content.tagName).toBe("PRE");
    expect(globalThis.document.querySelector("script")).toBeNull();
    expect(screen.getByText("zhipu · embedding-3 · 1024 维")).toBeInTheDocument();
    expect(screen.getByText("pii_email")).toBeInTheDocument();
    expect(screen.getByText("technical_decision")).toBeInTheDocument();
  });

  it("filters abnormal chunks and lets an administrator correct the final switch", async () => {
    const user = userEvent.setup();
    const abnormal = {
      id: "e4dd52c0-5063-42f6-b536-24b102f9756a",
      document_version_id: versionId,
      chunk_index: 0,
      heading_path: ["Contact"],
      content: "Email redacted",
      content_hash: "a".repeat(64),
      character_count: 14,
      enabled: false,
      auto_indexable: false,
      quality_issues: [{ code: "pii_email", severity: "warning" }],
      extracted_metadata: {},
      quality_checked_at: "2026-07-15T08:00:02Z",
      quality_model: "deepseek-chat",
      quality_reason: "PII is excluded by default.",
      created_at: "2026-07-15T08:00:02Z",
    };
    const normal = {
      ...abnormal,
      id: "f1dd52c0-5063-42f6-b536-24b102f9756a",
      chunk_index: 1,
      enabled: true,
      auto_indexable: true,
      quality_issues: [],
      quality_reason: "Technical content.",
    };
    listChunksMock.mockResolvedValue([abnormal, normal]);
    updateChunkMock.mockResolvedValue({ ...abnormal, enabled: true });
    renderPage();

    await screen.findByRole("heading", { name: "Chunk 0" });
    await user.click(screen.getByRole("button", { name: "只看异常 Chunk" }));
    expect(screen.queryByRole("heading", { name: "Chunk 1" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "启用 Chunk 0" }));

    expect(updateChunkMock).toHaveBeenCalledWith(abnormal.id, { enabled: true });
    expect(await screen.findByRole("button", { name: "禁用 Chunk 0" })).toBeInTheDocument();
  });

  it("redirects an unauthenticated administrator to login", async () => {
    listChunksMock.mockRejectedValue(
      new ApiError(401, "authentication_required", "raw cookie details"),
    );
    renderPage();

    expect(await screen.findByText("管理员登录")).toBeInTheDocument();
    expect(screen.queryByText("raw cookie details")).not.toBeInTheDocument();
  });
});
