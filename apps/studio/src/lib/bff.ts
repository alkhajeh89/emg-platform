import type { EntityResponse, SessionResponse } from "./contracts";

const BFF_PREFIX = "/bff";
const CSRF_COOKIE_NAME =
  process.env.NEXT_PUBLIC_STUDIO_CSRF_COOKIE_NAME ?? "__Host-emg_studio_csrf";

export class BffError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BFF_PREFIX}${path}`, {
    ...init,
    credentials: "include",
    headers: { Accept: "application/json", ...init?.headers },
  });

  if (!response.ok) {
    throw new BffError(`Studio BFF request failed (${response.status})`, response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function readCookie(name: string): string | undefined {
  const prefix = `${encodeURIComponent(name)}=`;
  return document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix))
    ?.slice(prefix.length);
}

export const bff = {
  loginUrl: `${BFF_PREFIX}/auth/login`,
  session: () => request<SessionResponse>("/auth/session"),
  entity: (entityId: string) =>
    request<EntityResponse>(
      `/api/knowledge-graph/v1/knowledge-graph/entities/${encodeURIComponent(entityId)}`,
    ),
  logout: async () => {
    const csrfToken = readCookie(CSRF_COOKIE_NAME);
    if (!csrfToken) {
      throw new BffError("The CSRF cookie is missing; re-authentication is required", 401);
    }
    await request<void>("/auth/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": decodeURIComponent(csrfToken) },
    });
  },
};
