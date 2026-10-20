export type ApiErrorBody = { error: { code: string; message: string; retryable: boolean; trace_id: string } };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public retryable = false) {
    super(message);
  }
}

let csrfToken: string | null = null;
export function setCsrf(token: string | null) {
  csrfToken = token;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (init.json !== undefined) headers["Content-Type"] = "application/json";
  if (init.method && init.method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers,
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
    credentials: "same-origin",
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const e = (data as ApiErrorBody | null)?.error;
    throw new ApiError(res.status, e?.code ?? "UNKNOWN", e?.message ?? `요청 실패 (${res.status})`, e?.retryable);
  }
  return data as T;
}

export async function loadMe(): Promise<{ id: string; role: string; session_id?: string; csrf_token: string } | null> {
  try {
    const me = await api<{ id: string; role: string; session_id?: string; csrf_token: string }>("/auth/me");
    setCsrf(me.csrf_token);
    return me;
  } catch {
    return null;
  }
}

export const uuid = () => crypto.randomUUID();
