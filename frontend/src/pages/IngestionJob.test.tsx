import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { getIngestionJob } from "../api/knowledgeDocuments";
import type { IngestionJob as IngestionJobRecord } from "../types/knowledgeDocument";
import { IngestionJob } from "./IngestionJob";

vi.mock("../api/knowledgeDocuments", () => ({
  getIngestionJob: vi.fn(),
}));

const jobId = "0dc5214a-bf26-42e2-8a51-bf50e54de6fa";
const job: IngestionJobRecord = {
  job_id: jobId,
  document_version_id: "2aa4a8d2-67aa-4136-b02a-7422c1595743",
  document_id: "ee1dc50f-6cf6-4bdc-b796-a260e810d551",
  document_title: "项目设计说明",
  version_number: 1,
  status: "processing",
  stage: "chunking",
  progress: 55,
  error_message: null,
  created_at: "2026-07-15T08:00:00Z",
  started_at: "2026-07-15T08:00:01Z",
  finished_at: null,
};

const getJobMock = vi.mocked(getIngestionJob);

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={[`/admin/jobs/${jobId}`]}>
      <Routes>
        <Route path="/admin/jobs/:jobId" element={<IngestionJob />} />
        <Route path="/admin/login" element={<div>管理员登录</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("IngestionJob", () => {
  beforeEach(() => {
    getJobMock.mockReset();
  });

  it("shows the document, current processing stage, and progress", async () => {
    getJobMock.mockResolvedValue(job);
    renderPage();

    expect(await screen.findByRole("heading", { name: "文档处理任务" })).toBeInTheDocument();
    expect(screen.getByText("项目设计说明 · v1")).toBeInTheDocument();
    expect(screen.getByText("processing")).toBeInTheDocument();
    expect(screen.getByText("切分")).toBeInTheDocument();
    expect(screen.getByText("55%")).toBeInTheDocument();
  });

  it("shows a safe failed state", async () => {
    getJobMock.mockResolvedValue({
      ...job,
      status: "failed",
      stage: "cleaning",
      progress: 25,
      error_message: "Markdown document is empty after cleaning.",
      finished_at: "2026-07-15T08:00:02Z",
    });
    renderPage();

    expect(await screen.findByText("failed")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Markdown document is empty after cleaning.",
    );
  });

  it("shows the embedding stage for a knowledge indexing job", async () => {
    getJobMock.mockResolvedValue({
      ...job,
      job_type: "knowledge_indexing",
      stage: "embedding",
      progress: 80,
    });
    renderPage();

    expect(await screen.findByRole("heading", { name: "知识索引任务" })).toBeInTheDocument();
    expect(screen.getByText("向量生成")).toBeInTheDocument();
  });

  it("redirects an unauthenticated administrator to login", async () => {
    getJobMock.mockRejectedValue(
      new ApiError(401, "authentication_required", "raw cookie details"),
    );
    renderPage();

    expect(await screen.findByText("管理员登录")).toBeInTheDocument();
    expect(screen.queryByText("raw cookie details")).not.toBeInTheDocument();
  });

  it("can retry after a transient status-query failure", async () => {
    const user = userEvent.setup();
    getJobMock
      .mockRejectedValueOnce(
        new ApiError(503, "service_unavailable", "raw database details"),
      )
      .mockResolvedValueOnce({ ...job, status: "completed", stage: "saving", progress: 100 });
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("暂时不可用");
    expect(screen.queryByText("raw database details")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("completed")).toBeInTheDocument();
    expect(getJobMock).toHaveBeenCalledTimes(2);
  });
});
