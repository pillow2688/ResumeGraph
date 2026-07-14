import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { loginAdmin } from "../api/auth";
import { ApiError } from "../api/client";
import { AdminLogin } from "./AdminLogin";

vi.mock("../api/auth", () => ({
  loginAdmin: vi.fn(),
}));

const loginAdminMock = vi.mocked(loginAdmin);

function renderLogin(): void {
  render(
    <MemoryRouter initialEntries={["/admin/login"]}>
      <Routes>
        <Route path="/admin/login" element={<AdminLogin />} />
        <Route path="/admin/projects" element={<div>项目管理页</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AdminLogin", () => {
  it("submits credentials and navigates without storing a token", async () => {
    const user = userEvent.setup();
    loginAdminMock.mockResolvedValue({
      admin: { id: "admin-id", username: "admin" },
    });
    renderLogin();

    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("密码"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "登录管理后台" }));

    expect(loginAdminMock).toHaveBeenCalledWith({
      username: "admin",
      password: "correct horse battery staple",
    });
    expect(await screen.findByText("项目管理页")).toBeInTheDocument();
  });

  it("shows a friendly message for invalid credentials", async () => {
    const user = userEvent.setup();
    loginAdminMock.mockRejectedValue(
      new ApiError(401, "invalid_credentials", "sensitive backend message"),
    );
    renderLogin();

    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("密码"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "登录管理后台" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码不正确");
    expect(screen.queryByText("sensitive backend message")).not.toBeInTheDocument();
  });

  it.each([
    {
      error: new ApiError(422, "invalid_request", "raw validation details"),
      message: "登录信息格式有误，请检查后重试。",
    },
    {
      error: new ApiError(503, "service_unavailable", "redis connection details"),
      message: "登录服务暂时不可用，请稍后重试。",
    },
  ])("sanitizes login service errors", async ({ error, message }) => {
    const user = userEvent.setup();
    loginAdminMock.mockRejectedValue(error);
    renderLogin();

    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("密码"), "not-shown-to-users");
    await user.click(screen.getByRole("button", { name: "登录管理后台" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText(error.message)).not.toBeInTheDocument();
  });
});
