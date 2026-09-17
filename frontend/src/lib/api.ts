export const TOKEN_KEY = "truman.token";
export const UNAUTHORIZED_EVENT = "truman:unauthorized";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage unavailable: the token lives for this page only
  }
}

class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function authHeaders(): HeadersInit {
  return { Authorization: `Bearer ${getToken()}` };
}

export async function api<T>(
  path: string,
  init: { method?: string; json?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { ...(authHeaders() as Record<string, string>) };
  if (init.json !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/v1${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.json === undefined ? undefined : JSON.stringify(init.json),
    signal: init.signal,
  });
  if (response.status === 401) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = body?.error ?? {};
    throw new ApiError(
      response.status,
      error.code ?? "http_error",
      error.message ?? `${response.status} ${response.statusText}`,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
