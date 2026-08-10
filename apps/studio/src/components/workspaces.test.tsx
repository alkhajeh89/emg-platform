import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import { I18nProvider } from "@/i18n/i18n";
import { Dashboard } from "./dashboard";
import { EntityWorkspace } from "./entity-workspace";
import { PlannedWorkspace } from "./planned-workspace";

function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }); }
function providers(node: React.ReactNode) { const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); return <I18nProvider><QueryClientProvider client={client}>{node}</QueryClientProvider></I18nProvider>; }

describe("Sprint 1 workspaces", () => {
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

  it("preserves the approved pilot entity BFF flow and canonical values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ item: { summary: { node_id: "pilot-entity-001", node_type: "person", label: "Pilot Entity", confidence: .81, classification: "INTERNAL" }, source: "emg-svc-knowledge-graph-writer", aliases: [], evidence: [], histories: [], metadata: {} }, revision_context: { revision_number: 1, committed_at: "2026-08-10T00:25:00Z", is_current_head: true } })));
    render(providers(<EntityWorkspace />));
    fireEvent.click(screen.getByRole("button", { name: "Explore entity" }));
    expect(await screen.findByRole("heading", { name: "Pilot Entity" })).toBeInTheDocument();
    expect(screen.getAllByText("pilot-entity-001").some((node) => node.getAttribute("dir") === "ltr")).toBe(true);
    expect(screen.getByText("INTERNAL")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("#1")).toHaveAttribute("dir", "ltr");
    expect(fetch).toHaveBeenCalledWith("/bff/api/knowledge-graph/v1/knowledge-graph/entities/pilot-entity-001", expect.objectContaining({ credentials: "include" }));
  });
});
