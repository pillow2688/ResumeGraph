interface BackendErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown> | null;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type ApiRequestOptions<TBody> = Omit<RequestInit, "body"> & {
  body?: TBody;
};

type ApiFormRequestOptions = Omit<RequestInit, "body"> & {
  body: FormData;
};

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function isBackendErrorEnvelope(value: unknown): value is BackendErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }

  const error = value.error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof error.code === "string" &&
    "message" in error &&
    typeof error.message === "string"
  );
}

async function readJson(response: Response): Promise<unknown> {
  if (!response.headers.get("Content-Type")?.includes("application/json")) {
    return null;
  }

  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function parseResponse<TResponse>(response: Response): Promise<TResponse> {
  const payload = await readJson(response);

  if (!response.ok) {
    if (isBackendErrorEnvelope(payload)) {
      throw new ApiError(response.status, payload.error.code, payload.error.message);
    }

    throw new ApiError(
      response.status,
      "unexpected_error",
      "请求暂时无法完成，请稍后重试。",
    );
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }

  return payload as TResponse;
}

export async function apiRequest<TResponse, TBody = never>(
  path: string,
  options: ApiRequestOptions<TBody> = {},
): Promise<TResponse> {
  const { body, headers, ...requestOptions } = options;
  const requestHeaders = Object.fromEntries(new Headers(headers).entries());
  const hasBody = body !== undefined;

  if (hasBody) {
    delete requestHeaders["content-type"];
    requestHeaders["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...requestOptions,
      credentials: "include",
      headers: requestHeaders,
      ...(hasBody ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    throw new ApiError(0, "network_error", "无法连接服务，请检查网络后重试。");
  }

  return parseResponse<TResponse>(response);
}

export async function apiFormRequest<TResponse>(
  path: string,
  options: ApiFormRequestOptions,
): Promise<TResponse> {
  const { body, headers, ...requestOptions } = options;
  const requestHeaders = Object.fromEntries(new Headers(headers).entries());
  delete requestHeaders["content-type"];
  delete requestHeaders["Content-Type"];

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...requestOptions,
      credentials: "include",
      headers: requestHeaders,
      body,
    });
  } catch {
    throw new ApiError(0, "network_error", "无法连接服务，请检查网络后重试。");
  }

  return parseResponse<TResponse>(response);
}

export async function apiStreamRequest<TBody>(
  path: string,
  body: TBody,
  signal?: AbortSignal,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "network_error", "无法连接服务，请检查网络后重试。");
  }

  if (!response.ok) {
    await parseResponse<never>(response);
  }
  return response;
}
