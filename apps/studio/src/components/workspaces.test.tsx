import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { I18nProvider, useI18n } from "@/i18n/i18n";
import { Dashboard } from "./dashboard";
import { EntityWorkspace } from "./entity-workspace";
import { PlannedWorkspace } from "./planned-workspace";
import { SearchWorkspace } from "./search-workspace";

const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));

function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }); }
function providers(node: React.ReactNode) { const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); return <I18nProvider><QueryClientProvider client={client}>{node}</QueryClientProvider></I18nProvider>; }

const entityResponse = { item: { summary: { node_id: "pilot/entity", node_type: "person", label: "Pilot Entity", confidence: .81, classification: "INTERNAL", created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-09T00:00:00Z" }, source: "emg-svc-knowledge-graph-writer", aliases: [], evidence: [], histories: [], metadata: {} }, revision_context: { revision_number: 1, committed_at: "2026-08-10T00:25:00Z", is_current_head: true } };
const searchResponse = {
  items: [
    { entity: entityResponse.item.summary, match_kind: "ALIAS_EXACT" },
    { entity: { ...entityResponse.item.summary, node_id: "entity/a b", label: "Second Entity", node_type: "project", classification: "CONFIDENTIAL" }, match_kind: "LABEL_PREFIX" },
  ],
  page_info: { limit: 20, returned_count: 2, next_cursor: "opaque.cursor.value", has_more: true },
  revision_context: { revision_number: 42, committed_at: "2026-08-10T00:25:00Z", is_current_head: true },
};

function LanguageControl() {
  const { setLocale } = useI18n();
  return <button type="button" onClick={() => setLocale("ar")}>العربية</button>;
}

describe("Studio workspaces", () => {
  beforeEach(() => {
    navigation.push.mockReset();
    navigation.replace.mockReset();
    Object.defineProperty(document, "cookie", { configurable: true, value: "__Host-emg_studio_csrf=csrf-value" });
    document.documentElement.lang = "en";
    document.documentElement.dir = "ltr";
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders an honest dashboard without fabricated metrics", () => {
    render(providers(<Dashboard />));
    expect(screen.getByRole("heading", { name: "Welcome to EMG Studio" })).toBeInTheDocument();
    expect(screen.getByText("No activity feed available")).toBeInTheDocument();
    expect(screen.getByText(/No events or counts are fabricated/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Explore pilot entity" })).toHaveAttribute("href", "/entities");
  });

  it("renders planned routes as explicitly unavailable", () => {
    render(providers(<PlannedWorkspace title="decisions" />));
    expect(screen.getByRole("heading", { name: "Decisions" })).toBeInTheDocument();
    expect(screen.getByText("Decisions · Planned")).toBeInTheDocument();
  });

  it("renders an entity deep link through the approved BFF flow and preserves canonical values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(response(url.includes("neighbors") ? { items: [], page_info: { limit: 20, returned_count: 0, next_cursor: null, has_more: false }, revision_context: entityResponse.revision_context } : entityResponse))));
    render(providers(<EntityWorkspace initialEntityId="pilot/entity" />));
    expect(await screen.findByRole("heading", { name: "Pilot Entity" })).toBeInTheDocument();
    expect(screen.getAllByText("pilot/entity").some((node) => node.getAttribute("dir") === "ltr")).toBe(true);
    expect(screen.getByText("INTERNAL")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("#1")).toHaveAttribute("dir", "ltr");
    expect(fetch).toHaveBeenCalledWith("/bff/api/knowledge-graph/v1/knowledge-graph/entities/pilot%2Fentity", expect.objectContaining({ credentials: "include" }));
    expect(await screen.findByText("No authorized relationships are returned for this entity.")).toBeInTheDocument();
  });

  it("navigates entity entry using a safely encoded canonical ID", () => {
    render(providers(<EntityWorkspace />));
    fireEvent.change(screen.getByLabelText("Entity identifier"), { target: { value: "entity/a b" } });
    fireEvent.submit(screen.getByLabelText("Entity identifier").closest("form")!);
    expect(navigation.push).toHaveBeenCalledWith("/entities/entity%2Fa%20b");
  });

  it("starts governed search without placing query state in the URL", () => {
    render(providers(<SearchWorkspace />));
    expect(screen.getByText("Ready to search")).toBeInTheDocument();
    expect(screen.getByLabelText("Search query")).toHaveFocus();
    expect(navigation.push).not.toHaveBeenCalled();
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("rejects an empty search locally without issuing a request", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(providers(<SearchWorkspace />));
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "   " } });
    fireEvent.submit(screen.getByRole("search"));
    expect(screen.getByText("Check your search")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("renders authorized governed results, safe match kinds, revision, and encoded links", async () => {
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    const storageRead = vi.spyOn(Storage.prototype, "getItem");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(searchResponse)));
    render(providers(<SearchWorkspace />));
    const query = "North acquisition";
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: query } });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByRole("heading", { name: "Pilot Entity" })).toBeInTheDocument();
    expect(screen.getByText("Exact alias")).toBeInTheDocument();
    expect(screen.getByText("Label prefix")).toBeInTheDocument();
    expect(screen.getByText("#42")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("pilot/entity")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("INTERNAL")).toHaveAttribute("dir", "ltr");
    expect(screen.getAllByRole("link", { name: "Open entity workspace" })[0]).toHaveAttribute("href", "/entities/pilot%2Fentity");
    expect(screen.getAllByRole("link", { name: "Open entity workspace" })[1]).toHaveAttribute("href", "/entities/entity%2Fa%20b");
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/bff/api/knowledge-graph/search");
    expect(String(url)).not.toContain(query);
    expect(init).toEqual(expect.objectContaining({ credentials: "include", method: "POST" }));
    expect(storageWrite).not.toHaveBeenCalled();
    expect(storageRead).not.toHaveBeenCalled();
    expect(screen.queryByText(/relevance/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/total/i)).not.toBeInTheDocument();
    expect(screen.queryByText("0.81")).not.toBeInTheDocument();
  });

  it("distinguishes empty, validation, backend, and session-expiry states", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...searchResponse, items: [], page_info: { limit: 20, returned_count: 0, next_cursor: null, has_more: false } })));
    const view = render(providers(<SearchWorkspace />));
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "missing" } });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByText("No authorized results")).toBeInTheDocument();
    view.unmount();
    vi.mocked(fetch).mockResolvedValue(response({ error: { error_code: "KNOWLEDGE_GRAPH_INVALID_SEARCH_REQUEST" } }, 400));
    const invalid = render(providers(<SearchWorkspace />));
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "bad" } });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByText("Check your search")).toBeInTheDocument();
    invalid.unmount();
    vi.mocked(fetch).mockResolvedValue(response({}, 500));
    const failed = render(providers(<SearchWorkspace />));
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "broken" } });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByText("Search unavailable")).toBeInTheDocument();
    failed.unmount();
    vi.mocked(fetch).mockResolvedValue(response({}, 401));
    render(providers(<SearchWorkspace />));
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "expired" } });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByText("Session expired")).toBeInTheDocument();
  });

  it("forwards opaque continuation unchanged, appends, and deduplicates by entity ID", async () => {
    const decode = vi.spyOn(globalThis, "atob");
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response(searchResponse))
      .mockResolvedValueOnce(response({
        ...searchResponse,
        items: [searchResponse.items[0], { entity: { ...entityResponse.item.summary, node_id: "third", label: "Third" }, match_kind: "ID_PREFIX" }],
        page_info: { limit: 20, returned_count: 2, next_cursor: null, has_more: false },
      })));
    render(providers(<SearchWorkspace />));
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "North" } });
    fireEvent.submit(screen.getByRole("search"));
    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("heading", { name: "Third" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "Pilot Entity" })).toHaveLength(1);
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[1][1]?.body))).toEqual({ q: "North", limit: 20, cursor: "opaque.cursor.value" });
    expect(decode).not.toHaveBeenCalled();
  });

  it("retains visible results on invalid continuation and offers a safe restart", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response(searchResponse))
      .mockResolvedValueOnce(response({ error: { error_code: "KNOWLEDGE_GRAPH_INVALID_SEARCH_CONTINUATION" } }, 400))
      .mockResolvedValueOnce(response({ ...searchResponse, page_info: { ...searchResponse.page_info, has_more: false, next_cursor: null } })));
    render(providers(<SearchWorkspace />));
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "North" } });
    fireEvent.submit(screen.getByRole("search"));
    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Continuation unavailable")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pilot Entity" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restart search" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[2][1]?.body))).toEqual({ q: "North", limit: 20 });
  });

  it("clears stale results as soon as a new query is typed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(searchResponse)));
    render(providers(<SearchWorkspace />));
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "North" } });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByRole("heading", { name: "Pilot Entity" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "South" } });
    expect(screen.queryByRole("heading", { name: "Pilot Entity" })).not.toBeInTheDocument();
    expect(screen.getByText("Ready to submit")).toBeInTheDocument();
  });

  it("renders Arabic RTL copy while preserving canonical technical values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...searchResponse, page_info: { ...searchResponse.page_info, has_more: false, next_cursor: null } })));
    render(providers(<><LanguageControl /><SearchWorkspace /></>));
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
    fireEvent.change(screen.getByLabelText("نص البحث"), { target: { value: "North" } });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByText("اسم بديل مطابق")).toBeInTheDocument();
    expect(screen.getByText("pilot/entity")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("INTERNAL")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("#42")).toHaveAttribute("dir", "ltr");
  });
});
