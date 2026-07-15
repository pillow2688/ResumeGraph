import type {
  InterviewAskRequest,
  InterviewAskResponse,
} from "../types/interview";
import { apiRequest } from "./client";

export function askInterviewQuestion(
  payload: InterviewAskRequest,
): Promise<InterviewAskResponse> {
  return apiRequest<InterviewAskResponse, InterviewAskRequest>(
    "/api/v1/interview/ask",
    { method: "POST", body: payload },
  );
}
