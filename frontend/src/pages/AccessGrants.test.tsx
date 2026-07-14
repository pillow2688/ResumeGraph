import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createAccessGrant,
  listAccessGrants,
  revokeAccessGrant,
} from "../api/accessGrants";
import { ApiError } from "../api/client";
import { listProjects } from "../api/projects";
import type { AccessGrant } from "../types/accessGrant";
import type { Project } from "../types/project";
import { AccessGrants } from "./AccessGrants";

vi.mock("../api/accessGrants", () => ({
  createAccessGrant: vi.fn(),
  listAccessGrants: vi.fn(),
  revokeAccessGrant: vi.fn(),
}));

vi.mock("../api/projects", () => ({
  listProjects: vi.fn(),
}));

const createAccessGrantMock = vi.mocked(createAccessGrant);
const listAccessGrantsMock = vi.mocked(listAccessGrants);
const listProjectsMock = vi.mocked(listProjects);
const revokeAccessGrantMock = vi.mocked(revokeAccessGrant);

const project: Project = {
  id: "a1a908a0-c0f8-40df-b76c-4e32f7d710ec",
  name: "ResumeGraph",
  description: "A grounded portfolio assistant.",
  created_at: "2026-07-14T08:00:00Z",
  updated_at: "2026-07-14T08:00:00Z",
};

const grant: AccessGrant = {
  id: "4d5f2718-c079-4cd1-a07d-ea11f5821d92",
  name: "Fictional Recruiter",
  expires_at: "2026-07-21T10:00:00Z",
  max_requests: 100,
  request_count: 0,
  revoked_at: null,
  created_at: "2026-07-14T10:00:00Z",
  projects: [{ id: project.id, name: project.name }],
};

function renderAccessGrants(): void {
  render(
    <MemoryRouter initialEntries={["/admin/access-grants"]}>
      <Routes>
        <Route path="/admin/access-grants" element={<AccessGrants />} />
        <Route path="/admin/login" element={<div>管理员登录页</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AccessGrants", () => {
  beforeEach(() => {
    createAccessGrantMock.mockReset();
    listAccessGrantsMock.mockReset();
    listProjectsMock.mockReset();
    revokeAccessGrantMock.mockReset();
  });

  it("creates a project-scoped grant and forgets the one-time token when closed", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    listProjectsMock.mockResolvedValue([project]);
    listAccessGrantsMock.mockResolvedValue([]);
    createAccessGrantMock.mockResolvedValue({
      grant,
      access_token: "rsg_fictional_one_time_access_code",
    });
    renderAccessGrants();

    await screen.findByText("还没有访问授权");
    await user.click(screen.getByRole("button", { name: "创建访问授权" }));
    await user.type(screen.getByLabelText("授权名称"), "Fictional Recruiter");
    await user.click(screen.getByRole("checkbox", { name: "ResumeGraph" }));
    await user.click(screen.getByRole("button", { name: "创建授权" }));

    expect(createAccessGrantMock).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Fictional Recruiter",
        max_requests: 100,
        project_ids: [project.id],
      }),
    );
    const tokenDialog = await screen.findByRole("alertdialog");
    expect(tokenDialog).toHaveTextContent("访问码只显示一次，请立即保存。");
    expect(tokenDialog).toHaveTextContent("rsg_fictional_one_time_access_code");

    await user.click(within(tokenDialog).getByRole("button", { name: "复制访问码" }));
    expect(writeText).toHaveBeenCalledWith("rsg_fictional_one_time_access_code");

    await user.click(within(tokenDialog).getByRole("button", { name: "我已保存，关闭" }));
    expect(screen.queryByText("rsg_fictional_one_time_access_code")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fictional Recruiter" })).toBeInTheDocument();
  });

  it("revokes an active grant after confirmation", async () => {
    const user = userEvent.setup();
    const revokedGrant = { ...grant, revoked_at: "2026-07-14T11:00:00Z" };
    listProjectsMock.mockResolvedValue([project]);
    listAccessGrantsMock.mockResolvedValue([grant]);
    revokeAccessGrantMock.mockResolvedValue(revokedGrant);
    renderAccessGrants();

    await user.click(await screen.findByRole("button", { name: "撤销授权" }));
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "确认撤销" }));

    expect(revokeAccessGrantMock).toHaveBeenCalledWith(grant.id);
    expect(await screen.findByText("授权已撤销")).toBeInTheDocument();
    expect(screen.getByText("已撤销")).toBeInTheDocument();
  });

  it("disables grant creation until a project exists", async () => {
    listProjectsMock.mockResolvedValue([]);
    listAccessGrantsMock.mockResolvedValue([]);
    renderAccessGrants();

    expect(await screen.findByText("请先创建至少一个项目")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建访问授权" })).toBeDisabled();
  });

  it("shows only the sanitized error when initial loading is unavailable", async () => {
    listAccessGrantsMock.mockRejectedValue(
      new ApiError(503, "service_unavailable", "redis connection details"),
    );
    listProjectsMock.mockResolvedValue([]);
    renderAccessGrants();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "授权服务暂时不可用，请稍后重试。",
    );
    expect(screen.queryByText("请先创建至少一个项目")).not.toBeInTheDocument();
    expect(screen.queryByText("redis connection details")).not.toBeInTheDocument();
  });

  it("redirects to admin login when the administrator session expires", async () => {
    listAccessGrantsMock.mockRejectedValue(
      new ApiError(401, "admin_authentication_required", "session internals"),
    );
    listProjectsMock.mockResolvedValue([]);
    renderAccessGrants();

    expect(await screen.findByText("管理员登录页")).toBeInTheDocument();
    expect(screen.queryByText("session internals")).not.toBeInTheDocument();
  });

  it("sanitizes a 422 grant creation error", async () => {
    const user = userEvent.setup();
    listProjectsMock.mockResolvedValue([project]);
    listAccessGrantsMock.mockResolvedValue([]);
    createAccessGrantMock.mockRejectedValue(
      new ApiError(422, "invalid_project_scope", "raw project scope details"),
    );
    renderAccessGrants();

    await screen.findByText("还没有访问授权");
    await user.click(screen.getByRole("button", { name: "创建访问授权" }));
    await user.type(screen.getByLabelText("授权名称"), "Invalid Grant");
    await user.click(screen.getByRole("checkbox", { name: "ResumeGraph" }));
    await user.click(screen.getByRole("button", { name: "创建授权" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "授权信息或项目选择有误，请检查后重试。",
    );
    expect(screen.queryByText("raw project scope details")).not.toBeInTheDocument();
  });
});
