import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createInterviewConversation,
  deleteInterviewConversation,
  streamInterviewQuestion,
} from "./interview";

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

describe("multi-turn interview API", () => {
  afterEach(() => vi.restoreAllMocks());

  it("creates and deletes an ephemeral conversation", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            conversation_id: "conversation-id",
            expires_at: "2026-07-16T11:00:00Z",
            remaining_requests: 20,
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(createInterviewConversation()).resolves.toMatchObject({
      conversation_id: "conversation-id",
    });
    await expect(deleteInterviewConversation("conversation-id")).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      credentials: "include",
    });
    expect(fetchMock.mock.calls[1]?.[0]).toContain("/conversation-id");
  });

  it("parses POST SSE across chunk boundaries and returns only the final payload", async () => {
    const response = {
      conversation_id: "conversation-id",
      status: "answered_with_boundary",
      answer: "当前使用 Redis 保存 Session。",
      citations: [],
      agent_trace: {
        agents_used: ["project_agent", "verification_agent"],
        public_path: ["查询项目资料", "验证回答"],
      },
      context: {
        active_project_ids: ["resumegraph-project"],
        active_technical_topics: ["Redis"],
        turn_number: 1,
      },
      remaining_requests: 19,
    };
    const completed = `event: answer_completed\ndata: ${JSON.stringify({
      event_type: "answer_completed",
      public_message: "回答已完成",
      timestamp: "2026-07-16T10:00:02Z",
      progress: 100,
      response,
    })}\n\n`;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([
        "event: routing_started\ndata: {\"event_type\":\"routing_started\",",
        '"public_message":"正在理解问题","timestamp":"2026-07-16T10:00:00Z","progress":5}\n\n',
        completed.slice(0, 43),
        completed.slice(43),
      ]),
    );
    const events: string[] = [];

    await expect(
      streamInterviewQuestion(
        "conversation-id",
        {
          request_id: "request-id",
          question: "为什么使用 Redis？",
          project_ids: ["resumegraph-project"],
        },
        { onEvent: (event) => events.push(event.event_type) },
      ),
    ).resolves.toMatchObject({ status: "answered_with_boundary" });
    expect(events).toEqual(["routing_started", "answer_completed"]);
    const request = vi.mocked(fetch).mock.calls[0];
    expect(request?.[1]).toMatchObject({ method: "POST", credentials: "include" });
    expect(String(request?.[1]?.body)).not.toContain("system_prompt");
  });

  it("does not expose malformed or internal SSE payloads", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      streamResponse([
        'event: routing_started\ndata: {"event_type":"private_reasoning","public_message":"secret","timestamp":"x","progress":5}\n\n',
      ]),
    );
    const onEvent = vi.fn();

    await expect(
      streamInterviewQuestion(
        "conversation-id",
        { request_id: "request-id", question: "test" },
        { onEvent },
      ),
    ).rejects.toThrow("流式回答中断");
    expect(onEvent).not.toHaveBeenCalled();
  });
});
