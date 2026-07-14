import type { Admin, AdminLoginRequest, AdminLoginResponse } from "../types/auth";
import { apiRequest } from "./client";

const adminAuthPath = "/api/v1/admin/auth";

export function loginAdmin(credentials: AdminLoginRequest): Promise<AdminLoginResponse> {
  return apiRequest<AdminLoginResponse, AdminLoginRequest>(`${adminAuthPath}/login`, {
    method: "POST",
    body: credentials,
  });
}

export function getCurrentAdmin(): Promise<Admin> {
  return apiRequest<Admin>(`${adminAuthPath}/me`);
}

export function logoutAdmin(): Promise<void> {
  return apiRequest<void>(`${adminAuthPath}/logout`, { method: "POST" });
}

