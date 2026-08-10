import { bff } from "./bff";

describe("Studio BFF client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-emg_studio_csrf=csrf-value",
      writable: true,
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("uses only same-origin Studio BFF paths", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ authenticated: true }), { status: 200 }),
    );
    await bff.session();
    expect(fetch).toHaveBeenCalledWith("/bff/auth/session", expect.anything());
    expect(JSON.stringify(vi.mocked(fetch).mock.calls)).not.toContain("knowledge-graph:8000");
    expect(JSON.stringify(vi.mocked(fetch).mock.calls)).not.toContain("localhost:8003");
  });

  it("encodes entity identifiers before calling the read proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ item: {} }), { status: 200 }));
    await bff.entity("pilot/entity");
    expect(fetch).toHaveBeenCalledWith(
      "/bff/api/knowledge-graph/v1/knowledge-graph/entities/pilot%2Fentity",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("loads relationships only through the same-origin read proxy", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    await bff.neighbors("pilot/entity", "edge/cursor");
    expect(fetch).toHaveBeenCalledWith(
      "/bff/api/knowledge-graph/v1/knowledge-graph/entities/pilot%2Fentity/neighbors?limit=20&before_edge_id=edge%2Fcursor",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("echoes the CSRF cookie on logout", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));
    await bff.logout();
    expect(fetch).toHaveBeenCalledWith(
      "/bff/auth/logout",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: expect.objectContaining({ "X-CSRF-Token": "csrf-value" }),
      }),
    );
  });

  it("fails closed without a readable CSRF cookie", async () => {
    Object.defineProperty(document, "cookie", { configurable: true, value: "" });
    await expect(bff.logout()).rejects.toMatchObject({ status: 401 });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("never reads or writes token storage", () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    expect(bff.loginUrl).toBe("/bff/auth/login");
    expect(local).not.toHaveBeenCalled();
  });
});
