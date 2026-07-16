import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import {
  createPastedDocument,
  listProjectDocuments,
  uploadDocument,
} from "../api/knowledgeDocuments";
import { getProject } from "../api/projects";
import type {
  KnowledgeDocument,
  KnowledgeDocumentSummary,
} from "../types/knowledgeDocument";
import type { Project } from "../types/project";
import { ProjectDocuments } from "./ProjectDocuments";

vi.mock("../api/knowledgeDocuments", () => ({
  createPastedDocument: vi.fn(),
  listProjectDocuments: vi.fn(),
  uploadDocument: vi.fn(),
}));
vi.mock("../api/projects", () => ({ getProject: vi.fn() }));

const projectId = "a1a908a0-c0f8-40df-b76c-4e32f7d710ec";
const documentId = "ee1dc50f-6cf6-4bdc-b796-a260e810d551";
const project: Project = {
  id: projectId,
  name: "ResumeGraph",
  description: "A grounded portfolio assistant.",
  created_at: "2026-07-14T08:00:00Z",
  updated_at: "2026-07-14T08:00:00Z",
};
const summary: KnowledgeDocumentSummary = {
  id: documentId,
  project_id: projectId,
  document_scope: "project",
  knowledge_status: "implemented",
  title: "项目设计说明",
  created_at: "2026-07-15T08:00:00Z",
  updated_at: "2026-07-15T08:00:00Z",
  version_count: 1,
  latest_version: {
    id: "2aa4a8d2-67aa-4136-b02a-7422c1595743",
    document_id: documentId,
    version_number: 1,
    source_type: "pasted_markdown",
    original_filename: null,
    status: "draft",
    created_at: "2026-07-15T08:00:00Z",
    content_size_bytes: 18,
  },
};
const created: KnowledgeDocument = {
  ...summary,
  project: { id: projectId, name: "ResumeGraph" },
};

const getProjectMock = vi.mocked(getProject);
const listDocumentsMock = vi.mocked(listProjectDocuments);
const createPastedMock = vi.mocked(createPastedDocument);
const uploadMock = vi.mocked(uploadDocument);

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={[`/admin/projects/${projectId}/documents`]}>
      <Routes>
        <Route path="/admin/projects/:projectId/documents" element={<ProjectDocuments />} />
        <Route path="/admin/documents/:documentId" element={<div>文档详情目标</div>} />
        <Route path="/admin/login" element={<div>管理员登录</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProjectDocuments", () => {
  beforeEach(() => {
    getProjectMock.mockReset();
    listDocumentsMock.mockReset();
    createPastedMock.mockReset();
    uploadMock.mockReset();
    getProjectMock.mockResolvedValue(project);
    listDocumentsMock.mockResolvedValue([]);
  });

  it("shows project context and an empty document state", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "ResumeGraph 知识文档" })).toBeInTheDocument();
    expect(screen.getByText("还没有知识文档")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /返回项目列表/ })).toHaveAttribute(
      "href",
      "/admin/projects",
    );
  });

  it("renders document summaries and links to details", async () => {
    listDocumentsMock.mockResolvedValue([summary]);
    renderPage();

    expect(await screen.findByRole("link", { name: "项目设计说明" })).toHaveAttribute(
      "href",
      `/admin/documents/${documentId}`,
    );
    expect(screen.getByText(/1 个版本/)).toBeInTheDocument();
    expect(screen.getByText(/最新 v1/)).toBeInTheDocument();
    expect(screen.getByText("草稿待处理")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "去处理" })).toHaveAttribute(
      "href",
      `/admin/documents/${documentId}`,
    );
    expect(screen.getByText(/处理 → Chunk 审核 → 向量索引 → 发布/)).toBeInTheDocument();
  });

  it("makes a ready version visibly actionable for review and publication", async () => {
    listDocumentsMock.mockResolvedValue([
      {
        ...summary,
        latest_version: {
          ...summary.latest_version!,
          status: "ready_to_publish",
        },
      },
    ]);
    renderPage();

    expect(await screen.findByText("待发布")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "审核并发布" })).toHaveAttribute(
      "href",
      `/admin/documents/${documentId}`,
    );
  });

  it("creates a document from pasted Markdown and navigates to its detail", async () => {
    const user = userEvent.setup();
    createPastedMock.mockResolvedValue(created);
    renderPage();

    await screen.findByText("还没有知识文档");
    await user.click(screen.getByRole("button", { name: "创建知识文档" }));
    await user.type(screen.getByLabelText("文档标题"), " 项目设计说明 ");
    await user.type(screen.getByLabelText("Markdown 内容"), "# 项目背景");
    await user.selectOptions(screen.getByLabelText("资料身份"), "planned");
    await user.click(screen.getByRole("button", { name: "保存文档" }));

    expect(createPastedMock).toHaveBeenCalledWith(projectId, {
      title: "项目设计说明",
      content: "# 项目背景",
      knowledge_status: "planned",
    });
    expect(await screen.findByText("文档详情目标")).toBeInTheDocument();
  });

  it("uploads a Markdown file and shows local file metadata", async () => {
    const user = userEvent.setup();
    uploadMock.mockResolvedValue(created);
    renderPage();

    await screen.findByText("还没有知识文档");
    await user.click(screen.getByRole("button", { name: "创建知识文档" }));
    await user.click(screen.getByRole("tab", { name: "上传 .md 文件" }));
    await user.type(screen.getByLabelText("文档标题"), "项目设计说明");
    await user.selectOptions(screen.getByLabelText("资料身份"), "implemented");
    const file = new File(["# 文件内容"], "design.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText("选择 Markdown 文件"), file);

    expect(screen.getByText(/design\.md/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "上传并保存" }));
    expect(uploadMock).toHaveBeenCalledWith(
      projectId,
      "项目设计说明",
      file,
      "implemented",
    );
    expect(await screen.findByText("文档详情目标")).toBeInTheDocument();
  });

  it("rejects non-md and oversized files before upload", async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderPage();
    await screen.findByText("还没有知识文档");
    await user.click(screen.getByRole("button", { name: "创建知识文档" }));
    await user.click(screen.getByRole("tab", { name: "上传 .md 文件" }));

    await user.upload(
      screen.getByLabelText("选择 Markdown 文件"),
      new File(["plain"], "notes.txt", { type: "text/plain" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("只支持 .md 文件");

    const oversized = new File([new Uint8Array(1024 * 1024 + 1)], "large.md");
    await user.upload(screen.getByLabelText("选择 Markdown 文件"), oversized);
    expect(screen.getByRole("alert")).toHaveTextContent("不能超过 1 MiB");
    expect(uploadMock).not.toHaveBeenCalled();
  });

  it("redirects a 401 and sanitizes service errors", async () => {
    getProjectMock.mockRejectedValue(
      new ApiError(401, "admin_authentication_required", "raw cookie internals"),
    );
    renderPage();
    expect(await screen.findByText("管理员登录")).toBeInTheDocument();
    expect(screen.queryByText("raw cookie internals")).not.toBeInTheDocument();

    getProjectMock.mockResolvedValue(project);
    listDocumentsMock.mockRejectedValue(
      new ApiError(503, "service_unavailable", "database DSN"),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("文档服务暂时不可用");
    });
    expect(screen.queryByText("database DSN")).not.toBeInTheDocument();
  });

  it("shows a friendly missing project state", async () => {
    getProjectMock.mockRejectedValue(
      new ApiError(404, "project_not_found", "raw database details"),
    );
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("该项目不存在");
    expect(screen.queryByText("raw database details")).not.toBeInTheDocument();
  });
});
