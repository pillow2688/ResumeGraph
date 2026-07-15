import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { listDocumentChunks } from "../api/knowledgeDocuments";
import { DocumentChunks } from "./DocumentChunks";

vi.mock("../api/knowledgeDocuments", () => ({
  listDocumentChunks: vi.fn(),
}));

const versionId = "2aa4a8d2-67aa-4136-b02a-7422c1595743";
const listChunksMock = vi.mocked(listDocumentChunks);

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
