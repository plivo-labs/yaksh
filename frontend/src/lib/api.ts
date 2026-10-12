/** Where a token is kept, and the event that clears it when the server refuses it. The API
 * token opens every route but the review routes, which take a labeler's token. */
export interface Credential {
  key: string;
  refused: string;
}

export const API_TOKEN: Credential = { key: "yaksh.token", refused: "yaksh:unauthorized" };
export const LABELER_TOKEN: Credential = {
  key: "yaksh.labeler",
  refused: "yaksh:labeler-unauthorized",
};

function credentialFor(path: string): Credential {
  return path === "/review" || path.startsWith("/review/") ? LABELER_TOKEN : API_TOKEN;
}

export function getToken(credential: Credential): string {
  try {
    return localStorage.getItem(credential.key) ?? "";
  } catch {
    return "";
  }
}

export function setToken(credential: Credential, token: string): void {
  try {
    if (token) localStorage.setItem(credential.key, token);
    else localStorage.removeItem(credential.key);
  } catch {
    // storage unavailable: the token lives for this page only
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type ApiInit = {
  method?: string;
  json?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  headers?: Record<string, string>;
};

export async function request(path: string, init: ApiInit): Promise<Response> {
  const credential = credentialFor(path);
  const headers: Record<string, string> = {
    Authorization: `Bearer ${getToken(credential)}`,
    ...init.headers,
  };
  if (init.json !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/v1${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.json === undefined ? init.form : JSON.stringify(init.json),
    signal: init.signal,
  });
  if (response.status === 401) {
    window.dispatchEvent(new Event(credential.refused));
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
  return response;
}

export async function api<T>(path: string, init: ApiInit = {}): Promise<T> {
  const response = await request(path, init);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiBlob(path: string, init: ApiInit = {}): Promise<Blob> {
  return (await request(path, init)).blob();
}
