import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import {
  createPastedVersion,
  getDocument,
  getDocumentVersion,
  listDocumentVersions,
  processDocumentVersion,
  updateDocumentTitle,
  uploadVersion,
} from "../api/knowledgeDocuments";
import type {
  DocumentVersion,
  DocumentVersionSummary,
  KnowledgeDocument,
} from "../types/knowledgeDocument";
import { DocumentDetail } from "./DocumentDetail";

vi.mock("../api/knowledgeDocuments", () => ({
  createPastedVersion: vi.fn(),
  getDocument: vi.fn(),
  getDocumentVersion: vi.fn(),
  listDocumentVersions: vi.fn(),
  processDocumentVersion: vi.fn(),
  updateDocumentTitle: vi.fn(),
  uploadVersion: vi.fn(),
}));

const documentId = "ee1dc50f-6cf6-4bdc-b796-a260e810d551";
const versionOneSummary: DocumentVersionSummary = {
  id: "2aa4a8d2-67aa-4136-b02a-7422c1595743",
  document_id: documentId,
  version_number: 1,
  source_type: "pasted_markdown",
  original_filename: null,
  status: "draft",
  created_at: "2026-07-15T08:00:00Z",
  content_size_bytes: 36,
};
const versionOne: DocumentVersion = {
  ...versionOneSummary,
  raw_content: "# 第一版\n\n<script>alert('xss')</script>",
};
const versionTwo: DocumentVersion = {
  id: "23d8a1c5-3047-468e-8f91-d1a06c94a566",
  document_id: documentId,
  version_number: 2,
  source_type: "pasted_markdown",
  original_filename: null,
  raw_content: "# 第二版",
  status: "draft",
  created_at: "2026-07-15T09:00:00Z",
  content_size_bytes: 13,
};
const knowledgeDocument: KnowledgeDocument = {
  id: documentId,
  project_id: "a1a908a0-c0f8-40df-b76c-4e32f7d710ec",
  title: "项目设计说明",
  created_at: "2026-07-15T08:00:00Z",
  updated_at: "2026-07-15T08:00:00Z",
  version_count: 1,
  latest_version: versionOneSummary,
  project: {
    id: "a1a908a0-c0f8-40df-b76c-4e32f7d710ec",
    name: "ResumeGraph",
  },
};

const getDocumentMock = vi.mocked(getDocument);
const listVersionsMock = vi.mocked(listDocumentVersions);
const getVersionMock = vi.mocked(getDocumentVersion);
const updateTitleMock = vi.mocked(updateDocumentTitle);
const createVersionMock = vi.mocked(createPastedVersion);
const uploadVersionMock = vi.mocked(uploadVersion);
const processVersionMock = vi.mocked(processDocumentVersion);

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={[`/admin/documents/${documentId}`]}>
      <Routes>
        <Route path="/admin/documents/:documentId" element={<DocumentDetail />} />
        <Route path="/admin/jobs/:jobId" element={<div>文档处理任务</div>} />
        <Route path="/admin/login" element={<div>管理员登录</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DocumentDetail", () => {
  beforeEach(() => {
    getDocumentMock.mockReset();
    listVersionsMock.mockReset();
    getVersionMock.mockReset();
    updateTitleMock.mockReset();
    createVersionMock.mockReset();
    uploadVersionMock.mockReset();
    processVersionMock.mockReset();
    getDocumentMock.mockResolvedValue(knowledgeDocument);
    listVersionsMock.mockResolvedValue([versionOneSummary]);
    getVersionMock.mockResolvedValue(versionOne);
  });

  it("starts processing the selected draft and opens its job page", async () => {
    const user = userEvent.setup();
    processVersionMock.mockResolvedValue({
      job_id: "0dc5214a-bf26-42e2-8a51-bf50e54de6fa",
      status: "pending",
    });
    renderPage();
    await screen.findByTestId("markdown-preview");

    await user.click(screen.getByRole("button", { name: "开始处理" }));

    expect(processVersionMock).toHaveBeenCalledWith(versionOne.id);
    expect(await screen.findByText("文档处理任务")).toBeInTheDocument();
  });

  it("shows document context, version history, and a selectable raw preview", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "项目设计说明" })).toBeInTheDocument();
    expect(screen.getByText("所属项目：ResumeGraph")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "版本 v1" })).toBeInTheDocument();
    const preview = await screen.findByTestId("markdown-preview");
    expect(preview).toHaveTextContent("<script>alert('xss')</script>");
    expect(preview.tagName).toBe("PRE");
    expect(globalThis.document.querySelector("script")).toBeNull();
  });

  it("updates only the document title", async () => {
    const user = userEvent.setup();
    updateTitleMock.mockResolvedValue({ ...knowledgeDocument, title: "新标题" });
    renderPage();
    await screen.findByRole("heading", { name: "项目设计说明" });

    await user.click(screen.getByRole("button", { name: "修改标题" }));
    const title = screen.getByLabelText("文档标题");
    await user.clear(title);
    await user.type(title, " 新标题 ");
    await user.click(screen.getByRole("button", { name: "保存标题" }));

    expect(updateTitleMock).toHaveBeenCalledWith(documentId, { title: "新标题" });
    expect(await screen.findByRole("heading", { name: "新标题" })).toBeInTheDocument();
  });

  it("creates v2 from pasted Markdown, refreshes history, and selects it", async () => {
    const user = userEvent.setup();
    createVersionMock.mockResolvedValue(versionTwo);
    listVersionsMock
      .mockResolvedValueOnce([versionOneSummary])
      .mockResolvedValueOnce([versionTwo, versionOneSummary]);
    getVersionMock.mockImplementation(async (versionId) =>
      versionId === versionTwo.id ? versionTwo : versionOne,
    );
    renderPage();
    await screen.findByTestId("markdown-preview");

    await user.click(screen.getByRole("button", { name: "创建新版本" }));
    await user.type(screen.getByLabelText("Markdown 内容"), "# 第二版");
    await user.click(screen.getByRole("button", { name: "保存新版本" }));

    expect(createVersionMock).toHaveBeenCalledWith(documentId, { content: "# 第二版" });
    expect(await screen.findByRole("button", { name: "版本 v2" })).toBeInTheDocument();
    expect(await screen.findByTestId("markdown-preview")).toHaveTextContent("# 第二版");
  });

  it("keeps a successfully created version when history refresh fails", async () => {
    const user = userEvent.setup();
    createVersionMock.mockResolvedValue(versionTwo);
    listVersionsMock
      .mockResolvedValueOnce([versionOneSummary])
      .mockRejectedValueOnce(
        new ApiError(503, "service_unavailable", "raw database details"),
      );
    renderPage();
    await screen.findByTestId("markdown-preview");

    await user.click(screen.getByRole("button", { name: "创建新版本" }));
    await user.type(screen.getByLabelText("Markdown 内容"), "# 第二版");
    await user.click(screen.getByRole("button", { name: "保存新版本" }));

    expect(await screen.findByRole("button", { name: "版本 v2" })).toBeInTheDocument();
    expect(screen.getByTestId("markdown-preview")).toHaveTextContent("# 第二版");
    expect(screen.queryByRole("dialog", { name: "创建新版本" })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "新版本已保存，但版本列表刷新失败",
    );
    expect(screen.queryByText("raw database details")).not.toBeInTheDocument();
  });

  it("uploads a new .md version", async () => {
    const user = userEvent.setup();
    uploadVersionMock.mockResolvedValue({
      ...versionTwo,
      source_type: "markdown_file",
      original_filename: "second.md",
    });
    listVersionsMock.mockResolvedValueOnce([versionOneSummary]).mockResolvedValueOnce([
      { ...versionTwo, source_type: "markdown_file", original_filename: "second.md" },
      versionOneSummary,
    ]);
    renderPage();
    await screen.findByTestId("markdown-preview");
    await user.click(screen.getByRole("button", { name: "创建新版本" }));
    await user.click(screen.getByRole("tab", { name: "上传 .md 文件" }));
    const file = new File(["# 第二版"], "second.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText("选择 Markdown 文件"), file);
    await user.click(screen.getByRole("button", { name: "上传新版本" }));

    expect(uploadVersionMock).toHaveBeenCalledWith(documentId, file);
  });

  it("shows friendly duplicate, payload, and availability errors without raw details", async () => {
    const user = userEvent.setup();
    createVersionMock.mockRejectedValue(
      new ApiError(409, "duplicate_document_version", "hash constraint internals"),
    );
    renderPage();
    await screen.findByTestId("markdown-preview");
    await user.click(screen.getByRole("button", { name: "创建新版本" }));
    await user.type(screen.getByLabelText("Markdown 内容"), "# 第一版");
    await user.click(screen.getByRole("button", { name: "保存新版本" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("该内容已存在于版本历史中");
    expect(screen.queryByText("hash constraint internals")).not.toBeInTheDocument();

    createVersionMock.mockRejectedValue(
      new ApiError(413, "markdown_too_large", "server byte limit"),
    );
    await user.click(screen.getByRole("button", { name: "保存新版本" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Markdown 内容不能超过 1 MiB");

    createVersionMock.mockRejectedValue(
      new ApiError(422, "invalid_markdown_encoding", "codec traceback"),
    );
    await user.click(screen.getByRole("button", { name: "保存新版本" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Markdown 内容或编码无效");
    expect(screen.queryByText("codec traceback")).not.toBeInTheDocument();
  });

  it("shows title-save errors inside the open title dialog", async () => {
    const user = userEvent.setup();
    updateTitleMock.mockRejectedValue(
      new ApiError(503, "service_unavailable", "raw title persistence details"),
    );
    renderPage();
    await screen.findByRole("heading", { name: "项目设计说明" });

    await user.click(screen.getByRole("button", { name: "修改标题" }));
    const dialog = screen.getByRole("dialog", { name: "修改文档标题" });
    const title = within(dialog).getByLabelText("文档标题");
    await user.clear(title);
    await user.type(title, "新标题");
    await user.click(within(dialog).getByRole("button", { name: "保存标题" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "文档服务暂时不可用",
    );
    expect(screen.queryByText("raw title persistence details")).not.toBeInTheDocument();
  });

  it("switches between version contents and redirects 401 to login", async () => {
    const user = userEvent.setup();
    listVersionsMock.mockResolvedValue([versionTwo, versionOneSummary]);
    getVersionMock.mockImplementation(async (versionId) =>
      versionId === versionTwo.id ? versionTwo : versionOne,
    );
    renderPage();
    expect(await screen.findByTestId("markdown-preview")).toHaveTextContent("# 第二版");

    await user.click(screen.getByRole("button", { name: "版本 v1" }));
    await waitFor(() => {
      expect(screen.getByTestId("markdown-preview")).toHaveTextContent("# 第一版");
    });

    getDocumentMock.mockRejectedValue(
      new ApiError(401, "admin_authentication_required", "raw session"),
    );
    renderPage();
    expect(await screen.findByText("管理员登录")).toBeInTheDocument();
  });

  it("shows friendly missing document and missing version states", async () => {
    getDocumentMock.mockRejectedValue(
      new ApiError(404, "document_not_found", "raw row details"),
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("该知识文档不存在");
    expect(screen.queryByText("raw row details")).not.toBeInTheDocument();

    cleanup();
    getDocumentMock.mockResolvedValue(knowledgeDocument);
    listVersionsMock.mockResolvedValue([versionOneSummary]);
    getVersionMock.mockRejectedValue(
      new ApiError(404, "document_version_not_found", "raw version details"),
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("该文档版本不存在");
    expect(screen.queryByText("raw version details")).not.toBeInTheDocument();
  });
});
