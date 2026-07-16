import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createPublicDemoSession,
  getPublicDemoStatus,
} from "../api/publicDemo";
import { LandingPage } from "./LandingPage";

vi.mock("../api/publicDemo", () => ({
  getPublicDemoStatus: vi.fn(),
  createPublicDemoSession: vi.fn(),
}));

const statusMock = vi.mocked(getPublicDemoStatus);
const sessionMock = vi.mocked(createPublicDemoSession);

function renderLanding(): void {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/interview" element={<div>Interview destination</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LandingPage", () => {
  beforeEach(() => {
    statusMock.mockReset();
    sessionMock.mockReset();
    statusMock.mockResolvedValue({ available: true, candidate_name: "马腾飞" });
    sessionMock.mockResolvedValue({ redirect_url: "/interview" });
  });

  it("presents the public AI Interview product without an access-code form", async () => {
    renderLanding();

    expect(
      await screen.findByRole("heading", { name: "ResumeGraph AI Interview" }),
    ).toBeInTheDocument();
    expect(screen.getByText("你好，我是马腾飞。")).toBeInTheDocument();
    expect(screen.getAllByText("AI Interview Assistant")).toHaveLength(2);
    expect(screen.getByText("LangGraph")).toBeInTheDocument();
    expect(screen.getByText("RAG")).toBeInTheDocument();
    expect(screen.getByText("pgvector")).toBeInTheDocument();
    expect(screen.getByText("Multi-Agent")).toBeInTheDocument();
    expect(screen.queryByLabelText("访问码")).not.toBeInTheDocument();
  });

  it("creates the server-side Public Demo Session before entering Interview", async () => {
    const user = userEvent.setup();
    renderLanding();

    await user.click(await screen.findByRole("button", { name: "Start Interview" }));

    expect(sessionMock).toHaveBeenCalledOnce();
    expect(await screen.findByText("Interview destination")).toBeInTheDocument();
  });

  it("shows a friendly unavailable state and disables session creation", async () => {
    statusMock.mockResolvedValue({
      available: false,
      message: "AI Interview 尚未开放",
    });
    const user = userEvent.setup();
    renderLanding();

    expect(await screen.findByText("AI Interview 尚未开放")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Start Interview" });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(sessionMock).not.toHaveBeenCalled();
  });

  it("keeps API failures generic and never exposes backend details", async () => {
    statusMock.mockRejectedValue(new Error("postgresql://secret@database"));
    renderLanding();

    expect(
      await screen.findByText("AI Interview 暂时无法加载，请稍后再试。"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/postgresql:\/\//)).not.toBeInTheDocument();
  });
});
