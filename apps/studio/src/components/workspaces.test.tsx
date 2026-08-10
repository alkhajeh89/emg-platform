import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import { I18nProvider } from "@/i18n/i18n";
import { Dashboard } from "./dashboard";
import { EntityWorkspace } from "./entity-workspace";
import { PlannedWorkspace } from "./planned-workspace";
import { SearchWorkspace } from "./search-workspace";

const navigation = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));

function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }); }
function providers(node: React.ReactNode) { const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); return <I18nProvider><QueryClientProvider client={client}>{node}</QueryClientProvider></I18nProvider>; }

const entityResponse = { item: { summary: { node_id: "pilot/entity", node_type: "person", label: "Pilot Entity", confidence: .81, classification: "INTERNAL", created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-09T00:00:00Z" }, source: "emg-svc-knowledge-graph-writer", aliases: [], evidence: [], histories: [], metadata: {} }, revision_context: { revision_number: 1, committed_at: "2026-08-10T00:25:00Z", is_current_head: true } };

describe("Studio workspaces", () => {
  beforeEach(() => { navigation.push.mockReset(); navigation.replace.mockReset(); });
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

  it("supports exact-ID lookup and search-to-entity navigation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(entityResponse)));
    render(providers(<SearchWorkspace />));
    expect(screen.getByText("Ready for an exact lookup")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Canonical entity identifier"), { target: { value: "pilot/entity" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(await screen.findByRole("heading", { name: "Pilot Entity" })).toBeInTheDocument();
    expect(navigation.replace).toHaveBeenCalledWith("/search?q=pilot%2Fentity");
    expect(screen.getByRole("link", { name: "Open entity workspace" })).toHaveAttribute("href", "/entities/pilot%2Fentity");
  });

  it("distinguishes no authorized result, backend failure, and session expiry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({}, 404)));
    const view = render(providers(<SearchWorkspace initialQuery="missing" />));
    expect(await screen.findByText("No authorized result")).toBeInTheDocument();
    view.unmount();
    vi.mocked(fetch).mockResolvedValue(response({}, 500));
    render(providers(<SearchWorkspace initialQuery="broken" />));
    expect(await screen.findByText("Lookup unavailable")).toBeInTheDocument();
  });
});
