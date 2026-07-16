import type {
  ConversationAskRequest,
  ConversationAskResponse,
  ConversationCreateResponse,
  InterviewPublicEvent,
  InterviewPublicEventType,
  InterviewAskRequest,
  InterviewAskResponse,
} from "../types/interview";
import { ApiError, apiRequest, apiStreamRequest } from "./client";

export function askInterviewQuestion(
  payload: InterviewAskRequest,
): Promise<InterviewAskResponse> {
  return apiRequest<InterviewAskResponse, InterviewAskRequest>(
    "/api/v1/interview/ask",
    { method: "POST", body: payload },
  );
}

export function createInterviewConversation(): Promise<ConversationCreateResponse> {
  return apiRequest<ConversationCreateResponse>("/api/v1/interview/conversations", {
    method: "POST",
  });
}

export function deleteInterviewConversation(conversationId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/interview/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

const publicEventTypes = new Set<InterviewPublicEventType>([
  "question_received",
  "routing_started",
  "routing_completed",
  "profile_search_started",
  "profile_search_completed",
  "project_search_started",
  "project_search_completed",
  "technical_search_started",
  "technical_search_completed",
  "answer_drafting",
  "verification_started",
  "verification_completed",
  "answer_repairing",
  "answer_completed",
  "request_failed",
  "heartbeat",
]);

interface StreamOptions {
  signal?: AbortSignal;
  onEvent?: (event: InterviewPublicEvent) => void;
}

function parsePublicEvent(block: string): InterviewPublicEvent | null {
  const lines = block.split("\n");
  const eventType = lines
    .find((line) => line.startsWith("event:"))
    ?.slice("event:".length)
    .trim();
  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trimStart())
    .join("\n");
  if (!eventType || !publicEventTypes.has(eventType as InterviewPublicEventType) || !data) {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const event = value as Record<string, unknown>;
  const allowedKeys = new Set([
    "event_type",
    "public_message",
    "timestamp",
    "progress",
    "response",
  ]);
  if (
    Object.keys(event).some((key) => !allowedKeys.has(key)) ||
    event.event_type !== eventType ||
    typeof event.public_message !== "string" ||
    typeof event.timestamp !== "string" ||
    typeof event.progress !== "number"
  ) {
    return null;
  }
  return event as unknown as InterviewPublicEvent;
}

export async function streamInterviewQuestion(
  conversationId: string,
  payload: ConversationAskRequest,
  options: StreamOptions = {},
): Promise<ConversationAskResponse> {
  const response = await apiStreamRequest(
    `/api/v1/interview/conversations/${conversationId}/ask/stream`,
    payload,
    options.signal,
  );
  if (!response.body) {
    throw new ApiError(503, "stream_unavailable", "流式回答暂时不可用，请稍后重试。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed: ConversationAskResponse | null = null;
  let failureMessage: string | null = null;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = parsePublicEvent(block);
      if (!event) continue;
      options.onEvent?.(event);
      if (event.event_type === "request_failed") {
        failureMessage = event.public_message;
      }
      if (event.event_type === "answer_completed" && event.response) {
        completed = event.response;
      }
    }
    if (done) break;
  }

  if (completed) return completed;
  throw new ApiError(
    503,
    failureMessage ? "interview_request_failed" : "interview_stream_interrupted",
    failureMessage ?? "流式回答中断，请重新提交问题。",
  );
}
