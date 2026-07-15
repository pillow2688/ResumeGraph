import type { Admin } from "../types/auth";
import { apiRequest } from "./client";

export interface AdminUserCreateRequest {
  username: string;
  password: string;
}

const adminUsersPath = "/api/v1/admin/users";

export function listAdminUsers(): Promise<Admin[]> {
  return apiRequest<Admin[]>(adminUsersPath);
}

export function createAdminUser(payload: AdminUserCreateRequest): Promise<Admin> {
  return apiRequest<Admin, AdminUserCreateRequest>(adminUsersPath, {
    method: "POST",
    body: payload,
  });
}

export function deleteAdminUser(adminId: string): Promise<void> {
  return apiRequest<void>(`${adminUsersPath}/${adminId}`, { method: "DELETE" });
}
