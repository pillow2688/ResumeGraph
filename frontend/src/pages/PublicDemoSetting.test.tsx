import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { listAccessGrants } from "../api/accessGrants";
import { ApiError } from "../api/client";
import {
  getAdminPublicDemoConfig,
  updateAdminPublicDemoConfig,
} from "../api/publicDemo";
import type { AccessGrant } from "../types/accessGrant";
import { PublicDemoSetting } from "./PublicDemoSetting";

vi.mock("../api/accessGrants", () => ({ listAccessGrants: vi.fn() }));
vi.mock("../api/publicDemo", () => ({
  getAdminPublicDemoConfig: vi.fn(),
  updateAdminPublicDemoConfig: vi.fn(),
}));
vi.mock("../components/Layout", () => ({
  Layout: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

const grantsMock = vi.mocked(listAccessGrants);
const configMock = vi.mocked(getAdminPublicDemoConfig);
const updateMock = vi.mocked(updateAdminPublicDemoConfig);

const grant: AccessGrant = {
  id: "grant-1",
  name: "Public Demo Grant",
  expires_at: "2026-08-17T10:00:00Z",
  max_requests: 500,
  request_count: 20,
  revoked_at: null,
  created_at: "2026-07-17T10:00:00Z",
  projects: [
    { id: "project-1", name: "ResumeGraph" },
    { id: "project-2", name: "科研项目" },
  ],
};

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={["/admin/public-demo"]}>
      <Routes>
        <Route path="/admin/public-demo" element={<PublicDemoSetting />} />
        <Route path="/admin/login" element={<div>Admin login destination</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PublicDemoSetting", () => {
  beforeEach(() => {
    grantsMock.mockReset();
    configMock.mockReset();
    updateMock.mockReset();
    grantsMock.mockResolvedValue([grant]);
    configMock.mockResolvedValue({
      configured: true,
      candidate_name: "马腾飞",
      default_access_grant_id: grant.id,
      default_access_grant: grant,
      enabled: true,
      created_at: "2026-07-17T10:00:00Z",
      updated_at: "2026-07-17T10:00:00Z",
    });
    updateMock.mockResolvedValue({
      configured: true,
      candidate_name: "马腾飞",
      default_access_grant_id: grant.id,
      default_access_grant: grant,
      enabled: false,
    });
  });

  it("shows candidate, bound Grant, status and the effective public scope", async () => {
    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Public Demo" }),
    ).toBeInTheDocument();
    expect(await screen.findByDisplayValue("马腾飞")).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Public Demo Grant")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
    expect(screen.getByText("Profile 公开资料")).toBeInTheDocument();
    expect(screen.getByText("Technical 公开资料")).toBeInTheDocument();
    expect(screen.getByText("ResumeGraph")).toBeInTheDocument();
    expect(screen.getByText("科研项目")).toBeInTheDocument();
  });

  it("updates the singleton without creating a new permission system", async () => {
    const user = userEvent.setup();
    renderPage();

    const enabled = await screen.findByRole("checkbox", { name: "启用 Public Demo" });
    await user.click(enabled);
    await user.click(screen.getByRole("button", { name: "保存公开配置" }));

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith({
        candidate_name: "马腾飞",
        default_access_grant_id: grant.id,
        enabled: false,
      }),
    );
    expect(await screen.findByText("Public Demo 配置已保存")).toBeInTheDocument();
  });

  it("redirects to the existing admin login when authentication is missing", async () => {
    configMock.mockRejectedValue(
      new ApiError(401, "authentication_required", "private cookie details"),
    );
    renderPage();

    expect(await screen.findByText("Admin login destination")).toBeInTheDocument();
    expect(screen.queryByText("private cookie details")).not.toBeInTheDocument();
  });
});
