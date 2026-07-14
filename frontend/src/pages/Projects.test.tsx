import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import {
  createProject,
  deleteProject,
  listProjects,
  updateProject,
} from "../api/projects";
import type { Project } from "../types/project";
import { Projects } from "./Projects";

vi.mock("../api/projects", () => ({
  createProject: vi.fn(),
  deleteProject: vi.fn(),
  listProjects: vi.fn(),
  updateProject: vi.fn(),
}));

const createProjectMock = vi.mocked(createProject);
const deleteProjectMock = vi.mocked(deleteProject);
const listProjectsMock = vi.mocked(listProjects);
const updateProjectMock = vi.mocked(updateProject);

const project: Project = {
  id: "a1a908a0-c0f8-40df-b76c-4e32f7d710ec",
  name: "ResumeGraph",
  description: "A grounded portfolio assistant.",
  created_at: "2026-07-14T08:00:00Z",
  updated_at: "2026-07-14T08:00:00Z",
};

function renderProjects(): void {
  render(
    <MemoryRouter initialEntries={["/admin/projects"]}>
      <Routes>
        <Route path="/admin/projects" element={<Projects />} />
        <Route path="/admin/login" element={<div>登录页</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Projects", () => {
  beforeEach(() => {
    createProjectMock.mockReset();
    deleteProjectMock.mockReset();
    listProjectsMock.mockReset();
    updateProjectMock.mockReset();
  });

  it("shows a loading state before the project request resolves", () => {
    listProjectsMock.mockReturnValue(new Promise(() => undefined));

    renderProjects();

    expect(screen.getByText("正在加载项目…")).toBeInTheDocument();
  });

  it("shows an empty state without an integration placeholder", async () => {
    listProjectsMock.mockResolvedValue([]);

    renderProjects();

    expect(await screen.findByText("还没有项目")).toBeInTheDocument();
    expect(screen.queryByText("Phase 2.1 API 联调待完成")).not.toBeInTheDocument();
  });

  it("shows a sanitized service error", async () => {
    listProjectsMock.mockRejectedValue(
      new ApiError(503, "service_unavailable", "raw backend response"),
    );

    renderProjects();

    expect(await screen.findByRole("alert")).toHaveTextContent("加载项目失败，请稍后重试");
    expect(screen.queryByText("raw backend response")).not.toBeInTheDocument();
  });

  it("redirects to admin login when the administrator session expires", async () => {
    listProjectsMock.mockRejectedValue(
      new ApiError(401, "admin_authentication_required", "session internals"),
    );

    renderProjects();

    expect(await screen.findByText("登录页")).toBeInTheDocument();
    expect(screen.queryByText("session internals")).not.toBeInTheDocument();
  });

  it("creates a project and shows a success notice", async () => {
    const user = userEvent.setup();
    listProjectsMock.mockResolvedValue([]);
    createProjectMock.mockResolvedValue(project);
    renderProjects();

    await screen.findByText("还没有项目");
    await user.click(screen.getByRole("button", { name: "创建项目" }));
    await user.type(screen.getByLabelText("项目名称"), "ResumeGraph");
    await user.type(screen.getByLabelText("项目描述"), "A grounded portfolio assistant.");
    await user.click(screen.getByRole("button", { name: "保存项目" }));

    expect(createProjectMock).toHaveBeenCalledWith({
      name: "ResumeGraph",
      description: "A grounded portfolio assistant.",
    });
    expect(await screen.findByText("项目已创建")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "ResumeGraph" })).toBeInTheDocument();
  });

  it("sanitizes a 422 project creation error", async () => {
    const user = userEvent.setup();
    listProjectsMock.mockResolvedValue([]);
    createProjectMock.mockRejectedValue(
      new ApiError(422, "invalid_project_request", "raw validation details"),
    );
    renderProjects();

    await screen.findByText("还没有项目");
    await user.click(screen.getByRole("button", { name: "创建项目" }));
    await user.type(screen.getByLabelText("项目名称"), "Invalid Project");
    await user.click(screen.getByRole("button", { name: "保存项目" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "输入内容有误，请检查后重试。",
    );
    expect(screen.queryByText("raw validation details")).not.toBeInTheDocument();
  });

  it("edits an existing project", async () => {
    const user = userEvent.setup();
    const updatedProject = { ...project, name: "ResumeGraph Admin" };
    listProjectsMock.mockResolvedValue([project]);
    updateProjectMock.mockResolvedValue(updatedProject);
    renderProjects();

    const card = await screen.findByTestId(`project-${project.id}`);
    await user.click(within(card).getByRole("button", { name: "编辑" }));
    const nameInput = screen.getByLabelText("项目名称");
    await user.clear(nameInput);
    await user.type(nameInput, "ResumeGraph Admin");
    await user.click(screen.getByRole("button", { name: "保存更改" }));

    expect(updateProjectMock).toHaveBeenCalledWith(project.id, {
      name: "ResumeGraph Admin",
      description: project.description,
    });
    expect(await screen.findByText("项目已更新")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "ResumeGraph Admin" })).toBeInTheDocument();
  });

  it("links each project to its knowledge documents", async () => {
    listProjectsMock.mockResolvedValue([project]);
    renderProjects();

    const card = await screen.findByTestId(`project-${project.id}`);
    expect(within(card).getByRole("link", { name: "知识文档" })).toHaveAttribute(
      "href",
      `/admin/projects/${project.id}/documents`,
    );
  });

  it("requires confirmation before deleting a project", async () => {
    const user = userEvent.setup();
    listProjectsMock.mockResolvedValue([project]);
    deleteProjectMock.mockResolvedValue(undefined);
    renderProjects();

    const card = await screen.findByTestId(`project-${project.id}`);
    await user.click(within(card).getByRole("button", { name: "删除" }));

    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("确认删除项目？")).toBeInTheDocument();
    expect(deleteProjectMock).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(deleteProjectMock).toHaveBeenCalledWith(project.id));
    expect(await screen.findByText("项目已删除")).toBeInTheDocument();
    expect(screen.queryByTestId(`project-${project.id}`)).not.toBeInTheDocument();
  });

  it("explains a project_in_use conflict without exposing the backend message", async () => {
    const user = userEvent.setup();
    listProjectsMock.mockResolvedValue([project]);
    deleteProjectMock.mockRejectedValue(
      new ApiError(409, "project_in_use", "raw project constraint details"),
    );
    renderProjects();

    const card = await screen.findByTestId(`project-${project.id}`);
    await user.click(within(card).getByRole("button", { name: "删除" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "确认删除",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "该项目仍被访问授权或知识文档使用，请先解除相关引用。",
    );
    expect(screen.queryByText("raw project constraint details")).not.toBeInTheDocument();
    expect(screen.getByTestId(`project-${project.id}`)).toBeInTheDocument();
  });
});
