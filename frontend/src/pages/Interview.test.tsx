import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { askInterviewQuestion } from "../api/interview";
import { getRecruiterSession, logoutRecruiter } from "../api/recruiterAccess";
import { Interview } from "./Interview";

vi.mock("../api/interview", () => ({
  askInterviewQuestion: vi.fn(),
}));

vi.mock("../api/recruiterAccess", () => ({
  getRecruiterSession: vi.fn(),
  logoutRecruiter: vi.fn(),
}));

const askInterviewQuestionMock = vi.mocked(askInterviewQuestion);
const getRecruiterSessionMock = vi.mocked(getRecruiterSession);
const logoutRecruiterMock = vi.mocked(logoutRecruiter);

const session = {
  grant_id: "grant-id",
  grant_name: "Fictional Interview Grant",
  expires_at: "2026-07-30T10:00:00Z",
  remaining_requests: 20,
  allowed_projects: [
    { id: "profile-project", name: "候选人简历与个人背景" },
    { id: "resumegraph-project", name: "ResumeGraph" },
  ],
};

function renderInterview(): void {
  render(
    <MemoryRouter initialEntries={["/interview"]}>
      <Routes>
        <Route path="/interview" element={<Interview />} />
        <Route path="/access" element={<div>访问码入口</div>} />
        <Route path="/portfolio" element={<div>Portfolio 页面</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function submitQuestion(question: string): Promise<void> {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("面试问题"), question);
  await user.click(screen.getByRole("button", { name: "发送问题" }));
}

describe("Interview", () => {
  beforeEach(() => {
    getRecruiterSessionMock.mockReset();
    askInterviewQuestionMock.mockReset();
    logoutRecruiterMock.mockReset();
    getRecruiterSessionMock.mockResolvedValue(session);
  });

  it("loads the current grant and selects all authorized projects by default", async () => {
    renderInterview();

    expect(
      await screen.findByRole("heading", { name: "AI 面试助手" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Fictional Interview Grant")).toBeInTheDocument();
    expect(screen.getByText("剩余 20 次")).toBeInTheDocument();
    expect(screen.getByLabelText("候选人简历与个人背景")).toBeChecked();
    expect(screen.getByLabelText("ResumeGraph")).toBeChecked();
    expect(
      screen.getByText(
        "这是我的 AI 面试助手，回答基于我授权发布的简历与项目资料生成，正式结论以本人面试回答为准。",
      ),
    ).toBeInTheDocument();
  });

  it("redirects an invalid recruiter session to the access page", async () => {
    getRecruiterSessionMock.mockRejectedValue(
      new ApiError(401, "recruiter_authentication_required", "internal session detail"),
    );

    renderInterview();

    expect(await screen.findByText("访问码入口")).toBeInTheDocument();
    expect(screen.queryByText("internal session detail")).not.toBeInTheDocument();
  });

  it("sends only selected project ids and renders an answer with citations", async () => {
    const user = userEvent.setup();
    askInterviewQuestionMock.mockResolvedValue({
      status: "answered",
      answer: "我在 ResumeGraph 中使用 Redis 保存短期 Session。",
      citations: [
        {
          citation_handle: "evidence_1",
          document_scope: "project",
          project_id: "resumegraph-project",
          project_name: "ResumeGraph",
          document_title: "项目设计文档",
          version_number: 1,
          heading_path: ["状态管理", "Redis"],
        },
      ],
      remaining_requests: 19,
    });
    renderInterview();
    await screen.findByRole("heading", { name: "AI 面试助手" });
    await user.click(screen.getByLabelText("候选人简历与个人背景"));

    await user.type(screen.getByLabelText("面试问题"), "为什么使用 Redis？");
    await user.click(screen.getByRole("button", { name: "发送问题" }));

    expect(askInterviewQuestionMock).toHaveBeenCalledWith({
      question: "为什么使用 Redis？",
      project_ids: ["resumegraph-project"],
    });
    expect(
      await screen.findByText("我在 ResumeGraph 中使用 Redis 保存短期 Session。"),
    ).toBeInTheDocument();
    expect(screen.getByText("项目设计文档 · v1")).toBeInTheDocument();
    expect(screen.getByText("状态管理 / Redis")).toBeInTheDocument();
    expect(screen.getByText("剩余 19 次")).toBeInTheDocument();
  });

  it("labels a profile citation without a fabricated project", async () => {
    askInterviewQuestionMock.mockResolvedValue({
      status: "answered",
      answer: "我本科毕业于虚构的星河大学。",
      citations: [
        {
          citation_handle: "evidence_1",
          document_scope: "profile",
          project_id: null,
          project_name: null,
          document_title: "教育背景",
          version_number: 1,
          heading_path: ["教育"],
        },
      ],
      remaining_requests: 19,
    });
    renderInterview();

    await submitQuestion("你的教育背景是什么？");

    expect(await screen.findByText("候选人 Profile")).toBeInTheDocument();
    expect(screen.getByText("教育背景 · v1")).toBeInTheDocument();
  });

  it("renders the fixed insufficient-evidence state without citation cards", async () => {
    askInterviewQuestionMock.mockResolvedValue({
      status: "insufficient_evidence",
      answer: "我目前提供的资料中没有记录这一点，因此无法给出准确回答。",
      citations: [],
      remaining_requests: 19,
    });
    renderInterview();

    await submitQuestion("项目的峰值 QPS 是多少？");

    expect(await screen.findByText("证据不足")).toBeInTheDocument();
    expect(
      screen.getByText("我目前提供的资料中没有记录这一点，因此无法给出准确回答。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/evidence_/)).not.toBeInTheDocument();
  });

  it("shows quota exhaustion and disables further submissions", async () => {
    askInterviewQuestionMock.mockRejectedValue(
      new ApiError(429, "request_quota_exhausted", "quota internals"),
    );
    renderInterview();

    await submitQuestion("为什么使用 Redis？");

    expect(await screen.findByRole("alert")).toHaveTextContent("当前访问授权的请求次数已用完。");
    expect(screen.queryByText("quota internals")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送问题" })).toBeDisabled();
  });

  it("prevents duplicate submission while a request is loading", async () => {
    let resolveRequest!: (value: Awaited<ReturnType<typeof askInterviewQuestion>>) => void;
    askInterviewQuestionMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRequest = resolve;
        }),
    );
    renderInterview();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("面试问题"), "为什么使用 Redis？");

    await user.click(screen.getByRole("button", { name: "发送问题" }));

    expect(screen.getByRole("button", { name: "正在生成回答…" })).toBeDisabled();
    expect(askInterviewQuestionMock).toHaveBeenCalledOnce();
    resolveRequest({
      status: "insufficient_evidence",
      answer: "我目前提供的资料中没有记录这一点，因此无法给出准确回答。",
      citations: [],
      remaining_requests: 19,
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "发送问题" })).toBeDisabled(),
    );
    expect(askInterviewQuestionMock).toHaveBeenCalledOnce();
    await user.type(screen.getByLabelText("面试问题"), "下一个问题");
    expect(screen.getByRole("button", { name: "发送问题" })).toBeEnabled();
  });

  it("keeps page history visible but never sends it with the next question", async () => {
    askInterviewQuestionMock
      .mockResolvedValueOnce({
        status: "answered",
        answer: "我本科就读于虚构大学。",
        citations: [
          {
            citation_handle: "evidence_1",
            document_scope: "profile",
            project_id: null,
            project_name: null,
            document_title: "教育背景",
            version_number: 1,
            heading_path: ["教育"],
          },
        ],
        remaining_requests: 19,
      })
      .mockResolvedValueOnce({
        status: "insufficient_evidence",
        answer: "我目前提供的资料中没有记录这一点，因此无法给出准确回答。",
        citations: [],
        remaining_requests: 18,
      });
    renderInterview();

    await submitQuestion("你的教育背景是什么？");
    expect(await screen.findByText("我本科就读于虚构大学。")).toBeInTheDocument();
    await submitQuestion("峰值 QPS 是多少？");

    expect(askInterviewQuestionMock).toHaveBeenCalledTimes(2);
    expect(askInterviewQuestionMock.mock.calls[1]?.[0]).toEqual({
      question: "峰值 QPS 是多少？",
      project_ids: ["profile-project", "resumegraph-project"],
    });
    expect(JSON.stringify(askInterviewQuestionMock.mock.calls[1]?.[0])).not.toContain(
      "你的教育背景是什么",
    );
    expect(screen.getByText("我本科就读于虚构大学。")).toBeInTheDocument();
  });

  it("sanitizes service errors and supports logout and return to Portfolio", async () => {
    askInterviewQuestionMock.mockRejectedValue(
      new ApiError(503, "interview_unavailable", "provider stack trace"),
    );
    logoutRecruiterMock.mockResolvedValue(undefined);
    renderInterview();

    await submitQuestion("为什么使用 Redis？");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "AI 面试服务暂时不可用，请稍后重试。",
    );
    expect(screen.queryByText("provider stack trace")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("link", { name: "返回 Portfolio" }));
    expect(await screen.findByText("Portfolio 页面")).toBeInTheDocument();
  });
});
