import type {
  PublicDemoAdminConfig,
  PublicDemoSession,
  PublicDemoStatus,
  PublicDemoUpdateRequest,
} from "../types/publicDemo";
import { apiRequest } from "./client";

const publicDemoPath = "/api/v1/public/demo";
const adminPublicDemoPath = "/api/v1/admin/public-demo";

export function getPublicDemoStatus(): Promise<PublicDemoStatus> {
  return apiRequest<PublicDemoStatus>(publicDemoPath);
}

export function createPublicDemoSession(): Promise<PublicDemoSession> {
  return apiRequest<PublicDemoSession>(`${publicDemoPath}/session`, {
    method: "POST",
  });
}

export function getAdminPublicDemoConfig(): Promise<PublicDemoAdminConfig> {
  return apiRequest<PublicDemoAdminConfig>(adminPublicDemoPath);
}

export function updateAdminPublicDemoConfig(
  payload: PublicDemoUpdateRequest,
): Promise<PublicDemoAdminConfig> {
  return apiRequest<PublicDemoAdminConfig, PublicDemoUpdateRequest>(
    adminPublicDemoPath,
    { method: "PUT", body: payload },
  );
}
