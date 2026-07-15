import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createPastedProfileDocument,
  listProfileDocuments,
  permanentlyDeleteDocument,
  unpublishDocument,
  uploadProfileDocument,
} from "../api/knowledgeDocuments";
import type { KnowledgeDocument, KnowledgeDocumentSummary } from "../types/knowledgeDocument";
import { ProfileDocuments } from "./ProfileDocuments";

vi.mock("../api/knowledgeDocuments", () => ({
  createPastedProfileDocument: vi.fn(),
  listProfileDocuments: vi.fn(),
  permanentlyDeleteDocument: vi.fn(),
  unpublishDocument: vi.fn(),
  uploadProfileDocument: vi.fn(),
}));

const documentId = "ee1dc50f-6cf6-4bdc-b796-a260e810d551";
const currentVersionId = "2aa4a8d2-67aa-4136-b02a-7422c1595743";
const summary: KnowledgeDocumentSummary = {
  id: documentId,
  project_id: null,
  document_scope: "profile",
  title: "AI Agent 岗位版简历",
  created_at: "2026-07-15T08:00:00Z",
  updated_at: "2026-07-15T08:00:00Z",
  version_count: 2,
  current_published_version_id: currentVersionId,
  current_published_version_number: 2,
  current_chunk_count: 12,
  current_enabled_chunk_count: 8,
  current_exact_duplicate_count: 2,
  current_hard_block_count: 1,
  current_embedding_count: 8,
  latest_version: {
    id: currentVersionId,
    document_id: documentId,
    version_number: 2,
    source_type: "pasted_markdown",
    original_filename: null,
    status: "published",
    created_at: "2026-07-15T08:00:00Z",
    content_size_bytes: 180,
  },
};
const created: KnowledgeDocument = { ...summary, project: null };

const listMock = vi.mocked(listProfileDocuments);
const createPastedMock = vi.mocked(createPastedProfileDocument);
const uploadMock = vi.mocked(uploadProfileDocument);
const unpublishMock = vi.mocked(unpublishDocument);
const permanentDeleteMock = vi.mocked(permanentlyDeleteDocument);

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={["/admin/profile-documents"]}>
      <Routes>
        <Route path="/admin/profile-documents" element={<ProfileDocuments />} />
        <Route path="/admin/documents/:documentId" element={<div>文档详情目标</div>} />
        <Route path="/admin/login" element={<div>管理员登录</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProfileDocuments", () => {
  beforeEach(() => {
    listMock.mockReset();
    createPastedMock.mockReset();
    uploadMock.mockReset();
    unpublishMock.mockReset();
    permanentDeleteMock.mockReset();
    listMock.mockResolvedValue([summary]);
  });

  it("shows multiple-profile management data and links to the shared document workflow", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Profile 全局资料" })).toBeInTheDocument();
    expect(screen.getByText(/所有有效面试官授权默认可检索/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Agent 岗位版简历" })).toHaveAttribute(
      "href",
      `/admin/documents/${documentId}`,
    );
    expect(screen.getByText(/当前发布 v2/)).toBeInTheDocument();
    expect(screen.getByText("Chunk 总数").nextSibling).toHaveTextContent("12");
    expect(screen.getByText("Enabled").nextSibling).toHaveTextContent("8");
    expect(screen.getByText("精确重复").nextSibling).toHaveTextContent("2");
    expect(screen.getByText("Hard Block").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Embedding").nextSibling).toHaveTextContent("8");
    expect(screen.getByText("已发布")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看已发布版本" })).toHaveAttribute(
      "href",
      `/admin/documents/${documentId}`,
    );
  });

  it("creates another profile document from pasted Markdown", async () => {
    const user = userEvent.setup();
    createPastedMock.mockResolvedValue(created);
    renderPage();

    await screen.findByText("AI Agent 岗位版简历");
    await user.click(screen.getByRole("button", { name: "新增 Profile 资料" }));
    await user.type(screen.getByLabelText("文档标题"), "算法岗位版简历");
    await user.type(screen.getByLabelText("Markdown 内容"), "# 虚构简历");
    await user.click(screen.getByRole("button", { name: "保存 Profile 资料" }));

    expect(createPastedMock).toHaveBeenCalledWith({
      title: "算法岗位版简历",
      content: "# 虚构简历",
    });
    expect(await screen.findByText("文档详情目标")).toBeInTheDocument();
    expect(uploadMock).not.toHaveBeenCalled();
  });

  it("keeps offline and permanent deletion as separate confirmations", async () => {
    const user = userEvent.setup();
    unpublishMock.mockResolvedValue({
      document_id: documentId,
      current_published_version_id: null,
    });
    permanentDeleteMock.mockResolvedValue(undefined);
    renderPage();

    await screen.findByText(/当前发布 v2/);
    await user.click(screen.getByRole("button", { name: "下线 AI Agent 岗位版简历" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("保留全部版本、Chunk、Embedding 和任务记录");
    await user.click(screen.getByRole("button", { name: "确认下线" }));
    await waitFor(() => expect(unpublishMock).toHaveBeenCalledWith(documentId));
    expect(screen.getByText(/当前未发布/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "永久删除 AI Agent 岗位版简历" }));
    const confirmation = screen.getByLabelText("输入文档标题以确认");
    const deleteButton = screen.getByRole("button", { name: "永久删除全部数据" });
    expect(deleteButton).toBeDisabled();
    await user.type(confirmation, "AI Agent 岗位版简历");
    expect(deleteButton).toBeEnabled();
    await user.click(deleteButton);

    await waitFor(() =>
      expect(permanentDeleteMock).toHaveBeenCalledWith(documentId, "AI Agent 岗位版简历"),
    );
    expect(screen.queryByText("AI Agent 岗位版简历")).not.toBeInTheDocument();
  });
});
