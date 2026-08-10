import type {
  EntityResponse,
  GovernedSearchRequest,
  GovernedSearchResponse,
  NeighborResponse,
  SessionResponse,
} from "./contracts";

const BFF_PREFIX = "/bff";
const CSRF_COOKIE_NAME =
  process.env.NEXT_PUBLIC_STUDIO_CSRF_COOKIE_NAME ?? "__Host-emg_studio_csrf";

export class BffError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly errorCode?: string,
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
    let errorCode: string | undefined;
    try {
      const body = (await response.json()) as { error?: { error_code?: unknown } };
      if (typeof body.error?.error_code === "string") errorCode = body.error.error_code;
    } catch {
      // Public status remains sufficient when the BFF returns no JSON envelope.
    }
    throw new BffError(`Studio BFF request failed (${response.status})`, response.status, errorCode);
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

function csrfHeaders(): Record<string, string> {
  const csrfToken = readCookie(CSRF_COOKIE_NAME);
  if (!csrfToken) {
    throw new BffError("The CSRF cookie is missing; re-authentication is required", 401);
  }
  return { "X-CSRF-Token": decodeURIComponent(csrfToken) };
}

export const bff = {
  loginUrl: `${BFF_PREFIX}/auth/login`,
  session: () => request<SessionResponse>("/auth/session"),
  entity: (entityId: string, revisionNumber?: number) =>
    request<EntityResponse>(
      `/api/knowledge-graph/v1/knowledge-graph/entities/${encodeURIComponent(entityId)}${revisionNumber ? `?revision_number=${revisionNumber}` : ""}`,
    ),
  neighbors: (entityId: string, cursor?: string, revisionNumber?: number) => {
    const query = new URLSearchParams({ limit: "20" });
    if (cursor) query.set("before_edge_id", cursor);
    if (revisionNumber) query.set("revision_number", String(revisionNumber));
    return request<NeighborResponse>(
      `/api/knowledge-graph/v1/knowledge-graph/entities/${encodeURIComponent(entityId)}/neighbors?${query}`,
    );
  },
  search: async (search: GovernedSearchRequest, signal?: AbortSignal) =>
    await request<GovernedSearchResponse>("/api/knowledge-graph/search", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify(search),
      signal,
    }),
  logout: async () => {
    await request<void>("/auth/logout", {
      method: "POST",
      headers: csrfHeaders(),
    });
  },
};
