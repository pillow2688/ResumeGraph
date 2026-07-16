import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createPastedTechnicalDocument,
  listTechnicalDocuments,
  uploadTechnicalDocument,
} from "../api/knowledgeDocuments";
import type {
  KnowledgeDocument,
  KnowledgeDocumentSummary,
} from "../types/knowledgeDocument";
import { TechnicalDocuments } from "./TechnicalDocuments";

vi.mock("../api/knowledgeDocuments", () => ({
  createPastedTechnicalDocument: vi.fn(),
  listTechnicalDocuments: vi.fn(),
  uploadTechnicalDocument: vi.fn(),
}));

const documentId = "ee1dc50f-6cf6-4bdc-b796-a260e810d551";
const summary: KnowledgeDocumentSummary = {
  id: documentId,
  project_id: null,
  document_scope: "technical",
  knowledge_status: "general_knowledge",
  title: "Redis 缓存雪崩",
  created_at: "2026-07-16T08:00:00Z",
  updated_at: "2026-07-16T08:00:00Z",
  version_count: 1,
  latest_version: null,
};
const created: KnowledgeDocument = { ...summary, project: null };

const listMock = vi.mocked(listTechnicalDocuments);
const createMock = vi.mocked(createPastedTechnicalDocument);
const uploadMock = vi.mocked(uploadTechnicalDocument);

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={["/admin/technical-documents"]}>
      <Routes>
        <Route path="/admin/technical-documents" element={<TechnicalDocuments />} />
        <Route path="/admin/documents/:documentId" element={<div>文档详情目标</div>} />
        <Route path="/admin/login" element={<div>管理员登录</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("TechnicalDocuments", () => {
  beforeEach(() => {
    listMock.mockReset();
    createMock.mockReset();
    uploadMock.mockReset();
    listMock.mockResolvedValue([summary]);
  });

  it("lists Technical knowledge with its non-project boundary", async () => {
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Technical 技术资料" }),
    ).toBeInTheDocument();
    expect(screen.getByText("通用技术原理")).toBeInTheDocument();
    expect(screen.getByText(/不能证明项目已经实现/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Redis 缓存雪崩" })).toHaveAttribute(
      "href",
      `/admin/documents/${documentId}`,
    );
  });

  it("requires and submits the general-knowledge classification", async () => {
    const user = userEvent.setup();
    createMock.mockResolvedValue(created);
    renderPage();

    await screen.findByText("Redis 缓存雪崩");
    await user.click(screen.getByRole("button", { name: "新增 Technical 资料" }));
    await user.type(screen.getByLabelText("文档标题"), "Redis 持久化");
    await user.type(screen.getByLabelText("Markdown 内容"), "# RDB 与 AOF");
    await user.selectOptions(
      screen.getByLabelText("资料身份"),
      "general_knowledge",
    );
    await user.click(screen.getByRole("button", { name: "保存 Technical 资料" }));

    expect(createMock).toHaveBeenCalledWith({
      title: "Redis 持久化",
      content: "# RDB 与 AOF",
      knowledge_status: "general_knowledge",
    });
    expect(await screen.findByText("文档详情目标")).toBeInTheDocument();
  });
});
