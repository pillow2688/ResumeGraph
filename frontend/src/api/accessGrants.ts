import type {
  AccessGrant,
  AccessGrantCreateRequest,
  AccessGrantCreateResponse,
} from "../types/accessGrant";
import { apiRequest } from "./client";

const accessGrantsPath = "/api/v1/admin/access-grants";

export function listAccessGrants(): Promise<AccessGrant[]> {
  return apiRequest<AccessGrant[]>(accessGrantsPath);
}

export function createAccessGrant(
  payload: AccessGrantCreateRequest,
): Promise<AccessGrantCreateResponse> {
  return apiRequest<AccessGrantCreateResponse, AccessGrantCreateRequest>(accessGrantsPath, {
    method: "POST",
    body: payload,
  });
}

export function revokeAccessGrant(grantId: string): Promise<AccessGrant> {
  return apiRequest<AccessGrant>(`${accessGrantsPath}/${grantId}/revoke`, {
    method: "POST",
  });
}

