import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { getRecruiterSession, logoutRecruiter } from "../api/recruiterAccess";
import { Portfolio } from "./Portfolio";

vi.mock("../api/recruiterAccess", () => ({
  getRecruiterSession: vi.fn(),
  logoutRecruiter: vi.fn(),
}));

const getRecruiterSessionMock = vi.mocked(getRecruiterSession);
const logoutRecruiterMock = vi.mocked(logoutRecruiter);

function renderPortfolio(): void {
  render(
    <MemoryRouter initialEntries={["/portfolio"]}>
      <Routes>
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/access" element={<div>访问码入口</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Portfolio", () => {
  beforeEach(() => {
    getRecruiterSessionMock.mockReset();
    logoutRecruiterMock.mockReset();
  });

  it("shows the current grant and authorized projects", async () => {
    getRecruiterSessionMock.mockResolvedValue({
      grant_id: "grant-id",
      grant_name: "Fictional Recruiter",
      expires_at: "2026-07-21T10:00:00Z",
      remaining_requests: 42,
      allowed_projects: [{ id: "project-id", name: "ResumeGraph" }],
    });
    renderPortfolio();

    expect(await screen.findByRole("heading", { name: "Fictional Recruiter" })).toBeInTheDocument();
    expect(screen.getByText("ResumeGraph")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("2026年7月21日")).toBeInTheDocument();
  });

  it("redirects to the access page when the recruiter session is invalid", async () => {
    getRecruiterSessionMock.mockRejectedValue(
      new ApiError(401, "recruiter_authentication_required", "session internals"),
    );
    renderPortfolio();

    expect(await screen.findByText("访问码入口")).toBeInTheDocument();
    expect(screen.queryByText("session internals")).not.toBeInTheDocument();
  });

  it("shows a sanitized service error without redirecting", async () => {
    getRecruiterSessionMock.mockRejectedValue(
      new ApiError(503, "service_unavailable", "database connection details"),
    );
    renderPortfolio();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "暂时无法加载授权项目，请稍后重试。",
    );
    expect(screen.queryByText("database connection details")).not.toBeInTheDocument();
  });

  it("logs out the recruiter and returns to the access page", async () => {
    const user = userEvent.setup();
    getRecruiterSessionMock.mockResolvedValue({
      grant_id: "grant-id",
      grant_name: "Fictional Recruiter",
      expires_at: "2026-07-21T10:00:00Z",
      remaining_requests: 42,
      allowed_projects: [{ id: "project-id", name: "ResumeGraph" }],
    });
    logoutRecruiterMock.mockResolvedValue(undefined);
    renderPortfolio();

    await user.click(await screen.findByRole("button", { name: "退出访问" }));

    expect(logoutRecruiterMock).toHaveBeenCalledOnce();
    expect(await screen.findByText("访问码入口")).toBeInTheDocument();
  });

  it("keeps the portfolio visible when recruiter logout is unavailable", async () => {
    const user = userEvent.setup();
    getRecruiterSessionMock.mockResolvedValue({
      grant_id: "grant-id",
      grant_name: "Fictional Recruiter",
      expires_at: "2026-07-21T10:00:00Z",
      remaining_requests: 42,
      allowed_projects: [{ id: "project-id", name: "ResumeGraph" }],
    });
    logoutRecruiterMock.mockRejectedValue(
      new ApiError(503, "service_unavailable", "redis connection details"),
    );
    renderPortfolio();

    await user.click(await screen.findByRole("button", { name: "退出访问" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "暂时无法退出访问，请稍后重试。",
    );
    expect(screen.queryByText("redis connection details")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fictional Recruiter" })).toBeInTheDocument();
  });
});
