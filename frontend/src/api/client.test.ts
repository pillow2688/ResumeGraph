import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFormRequest, apiRequest } from "./client";

describe("apiRequest", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("sends JSON with the administrator cookie enabled", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await apiRequest<{ ok: boolean }, { username: string }>("/api/v1/example", {
      method: "POST",
      body: { username: "admin" },
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/example", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "admin" }),
    });
  });

  it("converts the backend error envelope to ApiError", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "invalid_credentials",
            message: "Invalid administrator credentials.",
          },
        }),
        {
          status: 401,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    await expect(apiRequest("/api/v1/admin/auth/login")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      code: "invalid_credentials",
    });
  });

  it("sends multipart data with cookies and lets the browser set its boundary", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: "document-id" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const form = new FormData();
    form.set("title", "设计说明");
    form.set("file", new File(["# 内容"], "design.md", { type: "text/markdown" }));

    await apiFormRequest<{ id: string }>("/api/v1/admin/projects/project-id/documents/upload", {
      method: "POST",
      body: form,
      headers: { "X-Trace": "frontend-test" },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/admin/projects/project-id/documents/upload",
      {
        method: "POST",
        credentials: "include",
        headers: { "x-trace": "frontend-test" },
        body: form,
      },
    );
    const request = fetchMock.mock.calls[0]?.[1];
    expect(new Headers(request?.headers).has("Content-Type")).toBe(false);
  });

  it("does not expose an unstructured server response", async () => {
    fetchMock.mockResolvedValue(
      new Response("Traceback: database connection refused", {
        status: 500,
        headers: { "Content-Type": "text/plain" },
      }),
    );

    const request = apiRequest("/api/v1/admin/projects");

    await expect(request).rejects.toEqual(
      new ApiError(500, "unexpected_error", "请求暂时无法完成，请稍后重试。"),
    );
  });
});
