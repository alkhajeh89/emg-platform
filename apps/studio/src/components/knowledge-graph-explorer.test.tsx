import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { I18nProvider, useI18n } from "@/i18n/i18n";
import { KnowledgeGraphExplorer } from "./knowledge-graph-explorer";

function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function providers(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return (
    <I18nProvider>
      <QueryClientProvider client={client}>{node}</QueryClientProvider>
    </I18nProvider>
  );
}

const rootSummary = {
  node_id: "root/entity",
  node_type: "organization",
  label: "Root Entity",
  confidence: 0.92,
  classification: "INTERNAL",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-10T00:00:00Z",
};

const neighborSummary = {
  ...rootSummary,
  node_id: "neighbor one",
  node_type: "person",
  label: "Neighbor One",
  classification: "CONFIDENTIAL",
};

const secondNeighbor = {
  ...rootSummary,
  node_id: "neighbor-two",
  node_type: "project",
  label: "Neighbor Two",
};

const revision = {
  revision_number: 17,
  committed_at: "2026-08-10T00:25:00Z",
  is_current_head: true,
};

function entityResult(summary = rootSummary) {
  return {
    item: {
      summary,
      source: "emg-svc-knowledge-graph-writer",
      aliases: summary.node_id === rootSummary.node_id ? ["Root Alias"] : [],
      evidence: [],
      histories: [],
      metadata: {},
    },
    revision_context: revision,
  };
}

const firstNeighbors = {
  items: [
    {
      entity: neighborSummary,
      via_edge_id: "edge/root-neighbor",
      edge_type: "OWNS",
      confidence: 0.8,
      direction: "directed",
    },
  ],
  page_info: {
    limit: 20,
    returned_count: 1,
    next_cursor: "opaque/edge+cursor",
    has_more: true,
  },
  revision_context: revision,
};

function defaultFetch(url: string) {
  if (url.includes("/neighbors")) return Promise.resolve(response(firstNeighbors));
  if (url.includes("neighbor%20one")) return Promise.resolve(response(entityResult(neighborSummary)));
  return Promise.resolve(response(entityResult()));
}

function ArabicControl() {
  const { setLocale } = useI18n();
  return <button onClick={() => setLocale("ar")}>العربية</button>;
}

describe("Knowledge Graph Explorer", () => {
  beforeEach(() => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-emg_studio_csrf=csrf-value",
    });
    document.documentElement.lang = "en";
    document.documentElement.dir = "ltr";
    vi.stubGlobal("fetch", vi.fn().mockImplementation(defaultFetch));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("starts with governed in-memory root discovery", () => {
    render(providers(<KnowledgeGraphExplorer />));
    expect(screen.getByRole("heading", { name: "Knowledge Graph Explorer" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose an authorized starting entity" })).toBeInTheDocument();
    expect(screen.getByLabelText("Search query")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("discovers a root through same-origin governed search without URL or storage persistence", async () => {
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    const storageRead = vi.spyOn(Storage.prototype, "getItem");
    vi.mocked(fetch).mockResolvedValue(
      response({
        items: [{ entity: rootSummary, match_kind: "LABEL_EXACT" }],
        page_info: { limit: 20, returned_count: 1, next_cursor: null, has_more: false },
        revision_context: revision,
      }),
    );
    render(providers(<KnowledgeGraphExplorer />));
    const query = "private root search";
    fireEvent.change(screen.getByLabelText("Search query"), { target: { value: query } });
    fireEvent.submit(screen.getByRole("search"));
    expect(await screen.findByRole("link", { name: "Explore entity" })).toHaveAttribute(
      "href",
      "/knowledge-graph/root%2Fentity",
    );
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/bff/api/knowledge-graph/search");
    expect(String(url)).not.toContain(query);
    expect(init).toEqual(
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: expect.objectContaining({ "X-CSRF-Token": "csrf-value" }),
      }),
    );
    expect(storageWrite).not.toHaveBeenCalled();
    expect(storageRead).not.toHaveBeenCalled();
  });

  it("loads the canonical root and exactly one authorized neighbor page", async () => {
    render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    expect(await screen.findByRole("img", { name: "Authorized knowledge graph visualization" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Root Entity, INTERNAL" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Neighbor One, CONFIDENTIAL" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "OWNS, directed" })).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    const calls = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
    expect(calls).toContain("/bff/api/knowledge-graph/v1/knowledge-graph/entities/root%2Fentity");
    expect(calls).toContain("/bff/api/knowledge-graph/v1/knowledge-graph/entities/root%2Fentity/neighbors?limit=20&revision_number=17");
    expect(calls.some((url) => url.includes("neighbor%20one/neighbors"))).toBe(false);
  });

  it("selects and expands one node explicitly with per-node loading", async () => {
    let resolveExpansion: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation((url) => {
      const address = String(url);
      if (address.includes("neighbor%20one/neighbors")) {
        return new Promise<Response>((resolve) => {
          resolveExpansion = resolve;
        });
      }
      return defaultFetch(address);
    });
    render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    const neighbor = await screen.findByRole("button", { name: "Neighbor One, CONFIDENTIAL" });
    fireEvent.keyDown(neighbor, { key: "Enter" });
    expect(await screen.findByRole("heading", { name: "Neighbor One" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand selected entity" }));
    expect(screen.getByRole("button", { name: "Expanding entity…" })).toBeDisabled();
    await waitFor(() => expect(resolveExpansion).toBeDefined());
    resolveExpansion?.(
      response({
        items: [{ ...firstNeighbors.items[0], entity: secondNeighbor, via_edge_id: "edge/second" }],
        page_info: { limit: 20, returned_count: 1, next_cursor: null, has_more: false },
        revision_context: revision,
      }),
    );
    expect(await screen.findByRole("button", { name: "Neighbor Two, INTERNAL" })).toBeInTheDocument();
  });

  it("deduplicates canonical nodes and relationship identities", async () => {
    vi.mocked(fetch).mockImplementation((url) => {
      if (String(url).includes("/neighbors")) {
        return Promise.resolve(
          response({
            ...firstNeighbors,
            items: [firstNeighbors.items[0], firstNeighbors.items[0]],
            page_info: { ...firstNeighbors.page_info, has_more: false, next_cursor: null },
          }),
        );
      }
      return defaultFetch(String(url));
    });
    render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    expect(await screen.findAllByRole("button", { name: "Neighbor One, CONFIDENTIAL" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "OWNS, directed" })).toHaveLength(1);
  });

  it("forwards a node-local opaque cursor unchanged and appends authorized state", async () => {
    vi.mocked(fetch).mockImplementation((url) => {
      const address = String(url);
      if (address.includes("before_edge_id=")) {
        return Promise.resolve(
          response({
            items: [{ ...firstNeighbors.items[0], entity: secondNeighbor, via_edge_id: "edge/second" }],
            page_info: { limit: 20, returned_count: 1, next_cursor: null, has_more: false },
            revision_context: revision,
          }),
        );
      }
      return defaultFetch(address);
    });
    render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    fireEvent.click(await screen.findByRole("button", { name: "Load more relationships" }));
    expect(await screen.findByRole("button", { name: "Neighbor Two, INTERNAL" })).toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.some(([url]) =>
        String(url).includes("before_edge_id=opaque%2Fedge%2Bcursor"),
      ),
    ).toBe(true);
  });

  it("provides an accessible list over the same graph state with expansion and entity links", async () => {
    render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    await screen.findByRole("button", { name: "Neighbor One, CONFIDENTIAL" });
    fireEvent.click(screen.getByRole("button", { name: "Relationship list" }));
    const list = screen.getByRole("list", { name: "Relationship list" });
    expect(list).toHaveClass("accessible-graph-list");
    expect(screen.queryByText("edge/root-neighbor")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /OWNS/ })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "Open entity workspace" })[1]).toHaveAttribute(
      "href",
      "/entities/neighbor%20one",
    );
    expect(screen.getByRole("button", { name: "Expand entity" })).toBeEnabled();
  });

  it("shows canonical detail and relationship fields without hidden or total counts", async () => {
    render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    expect(await screen.findByRole("heading", { name: "Root Entity" })).toBeInTheDocument();
    expect(screen.getAllByText("root/entity").every((value) => value.getAttribute("dir") === "ltr")).toBe(true);
    expect(screen.getByText("INTERNAL")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("#17")).toHaveAttribute("dir", "ltr");
    fireEvent.click(await screen.findByRole("button", { name: "OWNS, directed" }));
    expect(screen.getByText("edge/root-neighbor")).toHaveAttribute("dir", "ltr");
    expect(screen.getAllByText("OWNS").some((value) => value.tagName === "DD" && value.getAttribute("dir") === "ltr")).toBe(true);
    expect(document.body.textContent).not.toMatch(/hidden|denied|total graph|total relationship/i);
  });

  it("keeps the visible graph unchanged when one expansion fails", async () => {
    vi.mocked(fetch).mockImplementation((url) => {
      const address = String(url);
      if (address.includes("neighbor%20one/neighbors")) return Promise.resolve(response({}, 503));
      return defaultFetch(address);
    });
    render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    fireEvent.click(await screen.findByRole("button", { name: "Neighbor One, CONFIDENTIAL" }));
    fireEvent.click(screen.getByRole("button", { name: "Expand selected entity" }));
    expect(await screen.findByText("This entity expansion is unavailable. The visible graph remains unchanged.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Root Entity, INTERNAL" })).toBeInTheDocument();
  });

  it("fails safely for root and session failures", async () => {
    vi.mocked(fetch).mockResolvedValue(response({}, 503));
    const failed = render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    expect(await screen.findByRole("heading", { name: "Graph unavailable" })).toBeInTheDocument();
    failed.unmount();
    vi.mocked(fetch).mockResolvedValue(response({}, 401));
    render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    expect(await screen.findByRole("heading", { name: "Graph unavailable" })).toBeInTheDocument();
  });

  it("renders Arabic RTL while canonical graph values remain LTR", async () => {
    render(providers(<><ArabicControl /><KnowledgeGraphExplorer initialRootId="root/entity" /></>));
    fireEvent.click(screen.getByRole("button", { name: "العربية" }));
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
    expect(await screen.findByRole("img", { name: "تصور الرسم البياني المعرفي المصرح به" })).toBeInTheDocument();
    expect(screen.getAllByText("root/entity").every((value) => value.getAttribute("dir") === "ltr")).toBe(true);
    expect(screen.getByText("INTERNAL")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("#17")).toHaveAttribute("dir", "ltr");
  });

  it("exposes responsive Explorer component classes without adding alternate data scope", async () => {
    const { container } = render(providers(<KnowledgeGraphExplorer initialRootId="root/entity" />));
    await screen.findByRole("img");
    expect(container.querySelector(".explorer-layout")).toBeInTheDocument();
    expect(container.querySelector(".explorer-stage")).toBeInTheDocument();
    expect(container.querySelector(".explorer-detail")).toBeInTheDocument();
  });
});
