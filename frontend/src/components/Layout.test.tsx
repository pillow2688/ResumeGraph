import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { Layout } from "./Layout";

const { logoutAdminMock } = vi.hoisted(() => ({
  logoutAdminMock: vi.fn(),
}));

vi.mock("../api/auth", () => ({
  logoutAdmin: logoutAdminMock,
}));

function renderLayout(): void {
  render(
    <MemoryRouter initialEntries={["/admin/projects"]}>
      <Routes>
        <Route
          path="/admin/projects"
          element={
            <Layout>
              <div>管理员内容</div>
            </Layout>
          }
        />
        <Route path="/admin/login" element={<div>管理员登录页</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Layout", () => {
  beforeEach(() => {
    logoutAdminMock.mockReset();
  });

  it("provides Phase 2.1 navigation and logs the administrator out", async () => {
    const user = userEvent.setup();
    logoutAdminMock.mockResolvedValue(undefined);
    renderLayout();

    expect(screen.getByRole("link", { name: "项目" })).toHaveAttribute(
      "href",
      "/admin/projects",
    );
    expect(screen.getByRole("link", { name: "访问授权" })).toHaveAttribute(
      "href",
      "/admin/access-grants",
    );
    await user.click(screen.getByRole("button", { name: "退出登录" }));

    expect(logoutAdminMock).toHaveBeenCalledOnce();
    expect(await screen.findByText("管理员登录页")).toBeInTheDocument();
  });

  it("keeps the administrator on the page when logout is unavailable", async () => {
    const user = userEvent.setup();
    logoutAdminMock.mockRejectedValue(
      new ApiError(503, "service_unavailable", "redis connection details"),
    );
    renderLayout();

    await user.click(screen.getByRole("button", { name: "退出登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "暂时无法退出登录，请稍后重试。",
    );
    expect(screen.queryByText("redis connection details")).not.toBeInTheDocument();
    expect(screen.getByText("管理员内容")).toBeInTheDocument();
  });
});
