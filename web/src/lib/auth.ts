/**
 * Auth client — talks to /auth on the API.
 *
 * The access token lives in memory only (never localStorage), so an XSS can't
 * lift a long-lived credential; the refresh token is an httpOnly cookie the JS
 * never sees. On load / on a 401 we silently `refresh()` against that cookie.
 */

const AUTH_BASE = (import.meta.env.VITE_API_BASE ?? "/api/v1") as string;

export type Membership = {
  org_id: string;
  org_name: string;
  org_slug: string;
  org_kind: string;
  role: string;
};

export type AuthUser = {
  id: string;
  email: string;
  display_name: string | null;
  is_platform_admin: boolean;
  memberships: Membership[];
};

type SessionResponse = { access_token: string; user: AuthUser };

// --- in-memory access token -------------------------------------------------
let accessToken: string | null = null;
export const getAccessToken = (): string | null => accessToken;

// api.ts calls this when a request 401s even after a refresh attempt, so the
// AuthProvider can drop the user back to the login screen.
let onAuthFailure: (() => void) | null = null;
export const setAuthFailureHandler = (fn: (() => void) | null): void => {
  onAuthFailure = fn;
};
export const emitAuthFailure = (): void => {
  accessToken = null;
  onAuthFailure?.();
};

async function postJson(path: string, body?: unknown): Promise<Response> {
  return fetch(`${AUTH_BASE}${path}`, {
    method: "POST",
    credentials: "include", // send/receive the refresh cookie
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    return typeof data?.detail === "string" ? data.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const res = await postJson("/auth/login", { email, password });
  if (!res.ok) throw new Error(await readError(res, "Sign in failed"));
  const data = (await res.json()) as SessionResponse;
  accessToken = data.access_token;
  return data.user;
}

export async function registerAccount(
  email: string,
  password: string,
  displayName?: string,
): Promise<AuthUser> {
  const res = await postJson("/auth/register", {
    email,
    password,
    display_name: displayName,
  });
  if (!res.ok) throw new Error(await readError(res, "Sign up failed"));
  const data = (await res.json()) as SessionResponse;
  accessToken = data.access_token;
  return data.user;
}

/** Swap the refresh cookie for a fresh access token. Returns null if no session. */
export async function refreshAccessToken(): Promise<string | null> {
  try {
    const res = await postJson("/auth/refresh");
    if (!res.ok) return null;
    const data = (await res.json()) as SessionResponse;
    accessToken = data.access_token;
    return accessToken;
  } catch {
    return null;
  }
}

export async function fetchMe(): Promise<AuthUser | null> {
  if (!accessToken) return null;
  const res = await fetch(`${AUTH_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    credentials: "include",
  });
  if (!res.ok) return null;
  const raw = (await res.json()) as AuthUser;
  // `/auth/me` may omit `memberships` for a traveller with no orgs; normalise it
  // so callers can rely on it being an array (a raw `.memberships[0]` used to
  // crash the Account page on the session-restore path).
  return { ...raw, memberships: raw.memberships ?? [] };
}

export async function logout(): Promise<void> {
  try {
    await postJson("/auth/logout");
  } catch {
    /* best effort */
  }
  accessToken = null;
}
