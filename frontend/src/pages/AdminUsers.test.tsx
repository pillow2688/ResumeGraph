import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { createAdminUser, deleteAdminUser, listAdminUsers } from "../api/adminUsers";
import { getCurrentAdmin } from "../api/auth";
import type { Admin } from "../types/auth";
import { AdminUsers } from "./AdminUsers";

vi.mock("../api/adminUsers", () => ({
  createAdminUser: vi.fn(),
  deleteAdminUser: vi.fn(),
  listAdminUsers: vi.fn(),
}));
vi.mock("../api/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/auth")>();
  return { ...actual, getCurrentAdmin: vi.fn() };
});

const listAdminUsersMock = vi.mocked(listAdminUsers);
const createAdminUserMock = vi.mocked(createAdminUser);
const deleteAdminUserMock = vi.mocked(deleteAdminUser);
const getCurrentAdminMock = vi.mocked(getCurrentAdmin);

const currentAdmin: Admin = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  username: "admin",
};
const reviewer: Admin = {
  id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  username: "reviewer",
};

function renderPage(): void {
  render(
    <MemoryRouter initialEntries={["/admin/users"]}>
      <Routes>
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/login" element={<div>登录页</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AdminUsers", () => {
  beforeEach(() => {
    listAdminUsersMock.mockReset();
    createAdminUserMock.mockReset();
    deleteAdminUserMock.mockReset();
    getCurrentAdminMock.mockReset();
    getCurrentAdminMock.mockResolvedValue(currentAdmin);
  });

  it("lists administrators and prevents self deletion", async () => {
    listAdminUsersMock.mockResolvedValue([currentAdmin, reviewer]);
    renderPage();

    const currentRow = await screen.findByTestId(`admin-${currentAdmin.id}`);
    expect(within(currentRow).getByText("当前登录账号")).toBeInTheDocument();
    expect(within(currentRow).getByRole("button", { name: "删除" })).toBeDisabled();
    expect(screen.getByTestId(`admin-${reviewer.id}`)).toBeInTheDocument();
  });

  it("creates an administrator without retaining the password", async () => {
    const user = userEvent.setup();
    listAdminUsersMock.mockResolvedValue([currentAdmin]);
    createAdminUserMock.mockResolvedValue(reviewer);
    renderPage();

    await screen.findByTestId(`admin-${currentAdmin.id}`);
    await user.click(screen.getByRole("button", { name: "新增管理员" }));
    await user.type(screen.getByLabelText("用户名"), "reviewer");
    await user.type(screen.getByLabelText("初始密码"), "fictional password");
    await user.click(screen.getByRole("button", { name: "确认新增" }));

    expect(createAdminUserMock).toHaveBeenCalledWith({
      username: "reviewer",
      password: "fictional password",
    });
    expect(await screen.findByTestId(`admin-${reviewer.id}`)).toBeInTheDocument();
    expect(screen.queryByDisplayValue("fictional password")).not.toBeInTheDocument();
  });

  it("requires confirmation before deleting another administrator", async () => {
    const user = userEvent.setup();
    listAdminUsersMock.mockResolvedValue([currentAdmin, reviewer]);
    deleteAdminUserMock.mockResolvedValue(undefined);
    renderPage();

    const row = await screen.findByTestId(`admin-${reviewer.id}`);
    await user.click(within(row).getByRole("button", { name: "删除" }));
    expect(deleteAdminUserMock).not.toHaveBeenCalled();
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "确认删除" }),
    );

    await waitFor(() => expect(deleteAdminUserMock).toHaveBeenCalledWith(reviewer.id));
    expect(screen.queryByTestId(`admin-${reviewer.id}`)).not.toBeInTheDocument();
  });

  it("redirects to login when the admin session is invalid", async () => {
    getCurrentAdminMock.mockRejectedValue(
      new ApiError(401, "authentication_required", "session details"),
    );
    listAdminUsersMock.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText("登录页")).toBeInTheDocument();
  });

  it("shows a safe conflict message for duplicate usernames", async () => {
    const user = userEvent.setup();
    listAdminUsersMock.mockResolvedValue([currentAdmin]);
    createAdminUserMock.mockRejectedValue(
      new ApiError(409, "admin_username_exists", "raw database details"),
    );
    renderPage();

    await screen.findByTestId(`admin-${currentAdmin.id}`);
    await user.click(screen.getByRole("button", { name: "新增管理员" }));
    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("初始密码"), "fictional password");
    await user.click(screen.getByRole("button", { name: "确认新增" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("用户名已存在");
    expect(screen.queryByText("raw database details")).not.toBeInTheDocument();
  });
});
