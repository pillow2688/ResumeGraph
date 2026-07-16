import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import {
  createInterviewConversation,
  deleteInterviewConversation,
  streamInterviewQuestion,
} from "../api/interview";
import { getRecruiterSession, logoutRecruiter } from "../api/recruiterAccess";
import type {
  ConversationAskResponse,
  InterviewPublicEvent,
} from "../types/interview";
import { Interview } from "./Interview";

vi.mock("../api/interview", () => ({
  createInterviewConversation: vi.fn(),
  deleteInterviewConversation: vi.fn(),
  streamInterviewQuestion: vi.fn(),
}));
vi.mock("../api/recruiterAccess", () => ({
  getRecruiterSession: vi.fn(),
  logoutRecruiter: vi.fn(),
}));

const createMock = vi.mocked(createInterviewConversation);
const deleteMock = vi.mocked(deleteInterviewConversation);
const streamMock = vi.mocked(streamInterviewQuestion);
const sessionMock = vi.mocked(getRecruiterSession);
const logoutMock = vi.mocked(logoutRecruiter);

const session = {
  grant_id: "grant-id",
  grant_name: "Fictional Interview Grant",
  expires_at: "2026-07-30T10:00:00Z",
  remaining_requests: 20,
  allowed_projects: [{ id: "resumegraph-project", name: "ResumeGraph" }],
};

const mixedAnswer: ConversationAskResponse = {
  conversation_id: "conversation-id",
  status: "answered_with_boundary",
  answer:
    "我目前使用 **Redis** 保存 Session。\n\n后续可以考虑：\n\n- TTL 随机化\n- 限流降级",
  citations: [
    {
      citation_handle: "evidence_1",
      knowledge_type: "project_fact",
      document_scope: "project",
      knowledge_status: "implemented",
      project_id: "resumegraph-project",
      project_name: "ResumeGraph",
      document_title: "Redis 使用说明",
      version_number: 1,
      heading_path: ["状态管理", "Redis"],
      excerpt: "Redis 用于保存服务端 Session。",
    },
    {
      citation_handle: "evidence_2",
      knowledge_type: "technical_knowledge",
      document_scope: "technical",
      knowledge_status: "general_knowledge",
      project_id: null,
      project_name: null,
      document_title: "Redis 缓存雪崩",
      version_number: 2,
      heading_path: ["TTL 随机化"],
      excerpt: "随机化 TTL 可减少 Key 同时失效。",
    },
    {
      citation_handle: "evidence_3",
      knowledge_type: "planned_solution",
      document_scope: "project",
      knowledge_status: "planned",
      project_id: "resumegraph-project",
      project_name: "ResumeGraph",
      document_title: "检索缓存规划",
      version_number: 1,
      heading_path: ["后续优化"],
      excerpt: "后续可缓存高频检索结果。",
    },
  ],
  agent_trace: {
    agents_used: ["project_agent", "technical_agent", "verification_agent"],
    public_path: ["查询项目资料", "补充技术原理", "验证回答"],
  },
  context: {
    active_project_ids: ["resumegraph-project"],
    active_technical_topics: ["Redis"],
    turn_number: 1,
  },
  remaining_requests: 19,
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

function emit(
  eventType: InterviewPublicEvent["event_type"],
  publicMessage: string,
  progress: number,
): InterviewPublicEvent {
  return {
    event_type: eventType,
    public_message: publicMessage,
    timestamp: "2026-07-16T10:00:00Z",
    progress,
  };
}

async function typeAndSend(question: string): Promise<void> {
  const user = userEvent.setup();
  const composer = await screen.findByLabelText("面试问题");
  await user.type(composer, question);
  await user.keyboard("{Enter}");
}

describe("Interview chat", () => {
  beforeEach(() => {
    createMock.mockReset();
    deleteMock.mockReset();
    streamMock.mockReset();
    sessionMock.mockReset();
    logoutMock.mockReset();
    sessionMock.mockResolvedValue(session);
    createMock.mockResolvedValue({
      conversation_id: "conversation-id",
      expires_at: "2026-07-16T11:00:00Z",
      remaining_requests: 20,
    });
    deleteMock.mockResolvedValue(undefined);
    streamMock.mockImplementation(async (_id, _payload, options) => {
      options?.onEvent?.(emit("routing_started", "正在理解问题", 5));
      options?.onEvent?.(emit("project_search_started", "正在查询项目资料", 30));
      options?.onEvent?.(emit("verification_started", "正在验证回答", 80));
      return mixedAnswer;
    });
  });

  it("creates an ephemeral conversation and shows a non-consuming welcome state", async () => {
    const user = userEvent.setup();
    renderInterview();

    expect(
      await screen.findByRole("heading", { name: "AI 面试助手" }),
    ).toBeInTheDocument();
    expect(createMock).toHaveBeenCalledOnce();
    expect(screen.getByText("Fictional Interview Grant")).toBeInTheDocument();
    expect(screen.getAllByText("ResumeGraph").length).toBeGreaterThan(0);
    expect(screen.getByText("剩余 20 次")).toBeInTheDocument();
    expect(screen.getByText(/正式结论以本人面试回答为准/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "为什么项目使用 Redis" }));
    expect(screen.getByLabelText("面试问题")).toHaveValue("为什么项目使用 Redis");
    expect(streamMock).not.toHaveBeenCalled();
  });

  it("shows recruiter messages on the right, public Agent progress, Markdown and citations", async () => {
    renderInterview();
    await typeAndSend("项目怎么解决 Redis 缓存雪崩？");

    const userMessage = await screen.findByText("项目怎么解决 Redis 缓存雪崩？");
    expect(userMessage.closest("article")).toHaveAttribute("data-side", "right");
    expect(await screen.findByText("正在验证回答")).toBeInTheDocument();
    const assistant = await screen.findByText(/我目前使用/);
    expect(assistant.closest("article")).toHaveAttribute("data-side", "left");
    expect(screen.getByText("Redis").tagName).toBe("STRONG");
    expect(screen.getByText("TTL 随机化")).toBeInTheDocument();
    expect(
      screen.getByText("以下回答包含当前实现情况和后续可考虑的方案。"),
    ).toBeInTheDocument();
    expect(screen.getByText(/回答路径：查询项目资料 → 补充技术原理 → 验证回答/)).toBeInTheDocument();
    expect(screen.getByText("项目事实")).toBeInTheDocument();
    expect(screen.getByText("技术原理")).toBeInTheDocument();
    expect(screen.getByText("后续方案")).toBeInTheDocument();
    expect(screen.getByText("当前技术主题：Redis")).toBeInTheDocument();
    expect(screen.getByText("当前对话：第 1 轮")).toBeInTheDocument();
    expect(screen.getByText("剩余 19 次")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /引用 2/ }));
    const drawer = screen.getByRole("dialog", { name: "引用详情" });
    expect(within(drawer).getByText("Redis 缓存雪崩")).toBeInTheDocument();
    expect(within(drawer).getByText(/随机化 TTL/)).toBeInTheDocument();
    expect(within(drawer).queryByText(/chunk_id|Embedding|SQL/)).not.toBeInTheDocument();
  });

  it("uses Enter to send, Shift+Enter for a newline, and ignores IME composition", async () => {
    const user = userEvent.setup();
    renderInterview();
    const composer = await screen.findByLabelText("面试问题");

    await user.type(composer, "第一行");
    await user.keyboard("{Shift>}{Enter}{/Shift}第二行");
    expect(composer).toHaveValue("第一行\n第二行");
    expect(streamMock).not.toHaveBeenCalled();

    composer.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        isComposing: true,
      }),
    );
    expect(streamMock).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(streamMock).toHaveBeenCalledOnce());
  });

  it("prevents duplicate submissions and supports stopping generation", async () => {
    let rejectStream!: (error: unknown) => void;
    streamMock.mockImplementation(
      (_id, _payload, options) =>
        new Promise((_resolve, reject) => {
          rejectStream = reject;
          options?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    const user = userEvent.setup();
    renderInterview();
    await user.type(await screen.findByLabelText("面试问题"), "为什么使用 Redis？");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(screen.getByRole("button", { name: "停止生成" })).toBeInTheDocument();
    expect(screen.getByLabelText("面试问题")).toBeDisabled();
    expect(streamMock).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "停止生成" }));
    expect(await screen.findByText(/已停止生成/)).toBeInTheDocument();
    expect(streamMock).toHaveBeenCalledOnce();
    rejectStream?.(new Error("ignored"));
  });

  it.each([
    ["partial_answer", "现有资料只能确认其中一部分。"],
    ["insufficient_evidence", "现有资料不足以支持准确回答。"],
    ["access_restricted", "该问题涉及当前未开放的项目资料。"],
  ] as const)("renders %s as natural language", async (status, message) => {
    streamMock.mockResolvedValue({
      ...mixedAnswer,
      status,
      answer: "这是自然回答正文。",
      citations: [],
    });
    renderInterview();
    await typeAndSend("请说明边界");

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText(status)).not.toBeInTheDocument();
  });

  it("renders Markdown without executing untrusted HTML", async () => {
    streamMock.mockResolvedValue({
      ...mixedAnswer,
      status: "answered",
      answer: "<script>window.hacked=true</script>\n\n`safe_code`",
      citations: [],
    });
    renderInterview();
    await typeAndSend("测试 Markdown");

    expect(await screen.findByText("safe_code")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(document.body.textContent).not.toContain("window.hacked");
  });

  it("clears the current Redis conversation and page state when starting over", async () => {
    const user = userEvent.setup();
    createMock
      .mockResolvedValueOnce({
        conversation_id: "conversation-id",
        expires_at: "2026-07-16T11:00:00Z",
        remaining_requests: 20,
      })
      .mockResolvedValueOnce({
        conversation_id: "new-conversation-id",
        expires_at: "2026-07-16T12:00:00Z",
        remaining_requests: 19,
      });
    renderInterview();
    await typeAndSend("为什么使用 Redis？");
    expect(await screen.findByText(/我目前使用/)).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "新建对话" })[0]!);
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith("conversation-id"));
    expect(createMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("为什么使用 Redis？")).not.toBeInTheDocument();
    expect(screen.queryByText("当前技术主题：Redis")).not.toBeInTheDocument();
    expect(screen.getByText("剩余 19 次")).toBeInTheDocument();
  });

  it("keeps stream failures inside the assistant message and never stores chat locally", async () => {
    const storageSpy = vi.spyOn(Storage.prototype, "setItem");
    streamMock.mockRejectedValue(
      new ApiError(503, "interview_stream_interrupted", "流式回答中断，请重新提交问题。"),
    );
    renderInterview();
    await typeAndSend("为什么使用 Redis？");

    expect(await screen.findByRole("alert")).toHaveTextContent("流式回答中断");
    expect(screen.getByRole("button", { name: "重新提交" })).toBeInTheDocument();
    expect(storageSpy).not.toHaveBeenCalled();
  });

  it("clears sensitive chat and redirects when authorization is invalid", async () => {
    sessionMock.mockRejectedValue(
      new ApiError(401, "recruiter_authentication_required", "cookie internals"),
    );
    renderInterview();

    expect(await screen.findByText("访问码入口")).toBeInTheDocument();
    expect(screen.queryByText("cookie internals")).not.toBeInTheDocument();
    expect(createMock).not.toHaveBeenCalled();
  });

  it("supports recruiter logout and a Portfolio return link", async () => {
    logoutMock.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderInterview();
    await screen.findByRole("heading", { name: "AI 面试助手" });

    expect(screen.getByRole("link", { name: "返回 Portfolio" })).toHaveAttribute(
      "href",
      "/portfolio",
    );
    await user.click(screen.getByRole("button", { name: "退出访问" }));
    expect(logoutMock).toHaveBeenCalledOnce();
    expect(await screen.findByText("访问码入口")).toBeInTheDocument();
  });
});
