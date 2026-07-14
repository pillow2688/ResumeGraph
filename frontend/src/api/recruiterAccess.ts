import type {
  AccessTokenExchangeRequest,
  RecruiterExchangeResponse,
  RecruiterSession,
} from "../types/accessGrant";
import { apiRequest } from "./client";

const recruiterAccessPath = "/api/v1/access";

export function exchangeAccessToken(
  payload: AccessTokenExchangeRequest,
): Promise<RecruiterExchangeResponse> {
  return apiRequest<RecruiterExchangeResponse, AccessTokenExchangeRequest>(
    `${recruiterAccessPath}/exchange`,
    { method: "POST", body: payload },
  );
}

export function getRecruiterSession(): Promise<RecruiterSession> {
  return apiRequest<RecruiterSession>(`${recruiterAccessPath}/me`);
}

export function logoutRecruiter(): Promise<void> {
  return apiRequest<void>(`${recruiterAccessPath}/logout`, { method: "POST" });
}

