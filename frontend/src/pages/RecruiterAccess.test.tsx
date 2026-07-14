import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { exchangeAccessToken } from "../api/recruiterAccess";
import { ApiError } from "../api/client";
import { RecruiterAccess } from "./RecruiterAccess";

vi.mock("../api/recruiterAccess", () => ({
  exchangeAccessToken: vi.fn(),
}));

const exchangeAccessTokenMock = vi.mocked(exchangeAccessToken);

function renderRecruiterAccess(): void {
  render(
    <MemoryRouter initialEntries={["/access"]}>
      <Routes>
        <Route path="/access" element={<RecruiterAccess />} />
        <Route path="/portfolio" element={<div>授权项目页</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RecruiterAccess", () => {
  beforeEach(() => {
    exchangeAccessTokenMock.mockReset();
  });

  it("exchanges the access token for a cookie-backed session", async () => {
    const user = userEvent.setup();
    exchangeAccessTokenMock.mockResolvedValue({
      recruiter: {
        grant_id: "grant-id",
        grant_name: "Fictional Recruiter",
        expires_at: "2026-07-21T10:00:00Z",
        remaining_requests: 100,
        allowed_projects: [{ id: "project-id", name: "ResumeGraph" }],
      },
    });
    renderRecruiterAccess();

    await user.type(screen.getByLabelText("访问码"), "rsg_fictional_access_code");
    await user.click(screen.getByRole("button", { name: "查看授权项目" }));

    expect(exchangeAccessTokenMock).toHaveBeenCalledWith({
      access_token: "rsg_fictional_access_code",
    });
    expect(await screen.findByText("授权项目页")).toBeInTheDocument();
  });

  it.each([
    new ApiError(401, "invalid_access_grant", "grant does not exist"),
    new ApiError(401, "invalid_access_grant", "grant expired"),
    new ApiError(401, "invalid_access_grant", "grant revoked"),
    new ApiError(401, "invalid_access_grant", "grant exhausted"),
  ])("uses one message for every invalid grant state", async (error) => {
    const user = userEvent.setup();
    exchangeAccessTokenMock.mockRejectedValue(error);
    renderRecruiterAccess();

    await user.type(screen.getByLabelText("访问码"), "invalid-code");
    await user.click(screen.getByRole("button", { name: "查看授权项目" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("访问码无效或已失效。");
    expect(screen.queryByText(error.message)).not.toBeInTheDocument();
  });
});
