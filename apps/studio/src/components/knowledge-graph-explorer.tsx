"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useI18n } from "@/i18n/i18n";
import { BffError, bff } from "@/lib/bff";
import type {
  EntityResponse,
  EntitySummary,
  GovernedSearchResponse,
  NeighborResponse,
} from "@/lib/contracts";
import { PageHeader } from "./ui";

const MAX_VISIBLE_NODES = 100;

interface VisibleEdge {
  id: string;
  anchorId: string;
  neighborId: string;
  edgeType: string;
  direction: string;
  confidence: number;
}

interface GraphState {
  nodes: Map<string, EntitySummary>;
  edges: Map<string, VisibleEdge>;
}

interface ExpansionState {
  loading: boolean;
  expanded: boolean;
  pageInfo?: NeighborResponse["page_info"];
  failed?: boolean;
}

interface Position {
  x: number;
  y: number;
}

function RootDiscovery() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<GovernedSearchResponse>();
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  async function search(cursor?: string) {
    if (!draft.trim() && !query) return;
    const submitted = cursor ? query : draft;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setFailed(false);
    if (!cursor) {
      setQuery(submitted);
      setResult(undefined);
    }
    try {
      const page = await bff.search(
        { q: submitted, limit: 20, ...(cursor ? { cursor } : {}) },
        controller.signal,
      );
      setResult((current) =>
        cursor && current
          ? {
              ...page,
              items: [
                ...new Map(
                  [...current.items, ...page.items].map((item) => [item.entity.node_id, item]),
                ).values(),
              ],
            }
          : page,
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (error instanceof BffError && error.status === 401) {
        void queryClient.invalidateQueries({ queryKey: ["session"] });
      }
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (draft.trim()) void search();
  }

  return (
    <section className="explorer-discovery" aria-labelledby="explorer-discovery-title">
      <div>
        <span className="eyebrow">{t("rootDiscovery")}</span>
        <h2 id="explorer-discovery-title">{t("findGraphRoot")}</h2>
        <p>{t("findGraphRootBody")}</p>
      </div>
      <form className="lookup" role="search" onSubmit={submit}>
        <label htmlFor="graph-root-search">{t("searchQueryLabel")}</label>
        <div className="lookup-row">
          <input
            id="graph-root-search"
            autoComplete="off"
            spellCheck={false}
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              setResult(undefined);
              setFailed(false);
            }}
            placeholder={t("searchQueryPlaceholder")}
          />
          <button type="submit" disabled={loading}>{t("searchAction")}</button>
        </div>
        <span className="hint">{t("graphSearchPrivacy")}</span>
      </form>
      {loading && <p className="availability-note" role="status">{t("searching")}</p>}
      {failed && <p className="availability-note" role="alert">{t("searchUnavailable")}</p>}
      {result && !result.items.length && <p className="empty-copy">{t("noResultsBody")}</p>}
      {result && result.items.length > 0 && (
        <ul className="root-result-list" aria-label={t("authorizedResults")}>
          {result.items.map((item) => (
            <li key={item.entity.node_id}>
              <div>
                <strong>{item.entity.label || item.entity.node_id}</strong>
                <span dir="ltr">{item.entity.node_id}</span>
              </div>
              <span className="classification" dir="ltr">{item.entity.classification}</span>
              <Link href={`/knowledge-graph/${encodeURIComponent(item.entity.node_id)}`}>
                {t("exploreEntity")}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {result?.page_info.has_more && result.page_info.next_cursor && (
        <div className="load-more-row">
          <button
            type="button"
            disabled={loading}
            onClick={() => void search(result.page_info.next_cursor ?? undefined)}
          >
            {loading ? t("loadingMore") : t("loadMore")}
          </button>
        </div>
      )}
    </section>
  );
}

function graphPositions(nodeIds: string[], rootId: string): Map<string, Position> {
  const positions = new Map<string, Position>([[rootId, { x: 400, y: 260 }]]);
  const others = nodeIds.filter((id) => id !== rootId).sort();
  const radius = others.length > 10 ? 205 : 180;
  others.forEach((id, index) => {
    const angle = (index / Math.max(others.length, 1)) * Math.PI * 2 - Math.PI / 2;
    positions.set(id, { x: 400 + Math.cos(angle) * radius, y: 260 + Math.sin(angle) * radius });
  });
  return positions;
}

function GraphCanvas({
  rootId,
  graph,
  selectedNodeId,
  selectedEdgeId,
  onSelectNode,
  onSelectEdge,
}: Readonly<{
  rootId: string;
  graph: GraphState;
  selectedNodeId: string;
  selectedEdgeId?: string;
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
}>) {
  const { t } = useI18n();
  const positions = useMemo(
    () => graphPositions([...graph.nodes.keys()], rootId),
    [graph.nodes, rootId],
  );

  function activate(event: KeyboardEvent<SVGGElement>, action: () => void) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  }

  return (
    <svg
      className="graph-canvas"
      viewBox="0 0 800 520"
      role="img"
      aria-label={t("graphVisualization")}
    >
      <g className="graph-edges">
        {[...graph.edges.values()].map((edge) => {
          const from = positions.get(edge.anchorId);
          const to = positions.get(edge.neighborId);
          if (!from || !to) return null;
          return (
            <g
              key={edge.id}
              role="button"
              tabIndex={0}
              aria-label={`${edge.edgeType}, ${edge.direction}`}
              className={selectedEdgeId === edge.id ? "graph-edge graph-edge--selected" : "graph-edge"}
              onClick={() => onSelectEdge(edge.id)}
              onKeyDown={(event) => activate(event, () => onSelectEdge(edge.id))}
            >
              <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} />
              <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 7}>{edge.edgeType}</text>
            </g>
          );
        })}
      </g>
      <g className="graph-nodes">
        {[...graph.nodes.values()].map((node) => {
          const position = positions.get(node.node_id);
          if (!position) return null;
          const selected = selectedNodeId === node.node_id;
          return (
            <g
              key={node.node_id}
              role="button"
              tabIndex={0}
              aria-label={`${node.label || node.node_id}, ${node.classification}`}
              className={selected ? "graph-node graph-node--selected" : "graph-node"}
              transform={`translate(${position.x},${position.y})`}
              onClick={() => onSelectNode(node.node_id)}
              onKeyDown={(event) => activate(event, () => onSelectNode(node.node_id))}
            >
              <rect x="-76" y="-28" width="152" height="56" rx="13" />
              <text className="graph-node__label" textAnchor="middle" y="-3">
                {(node.label || node.node_id).slice(0, 22)}
              </text>
              <text className="graph-node__type" textAnchor="middle" y="15">{node.node_type}</text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

function EntityDetailPanel({
  result,
  loading,
  selectedEdge,
}: Readonly<{
  result?: EntityResponse;
  loading: boolean;
  selectedEdge?: VisibleEdge;
}>) {
  const { t } = useI18n();
  if (loading) return <aside className="explorer-detail" aria-busy="true"><span className="spinner" />{t("loadingEntity")}</aside>;
  if (!result) return <aside className="explorer-detail"><p className="empty-copy">{t("selectNodePrompt")}</p></aside>;
  const { item, revision_context: revision } = result;
  return (
    <aside className="explorer-detail" aria-label={t("selectedEntityDetails")}>
      <header>
        <span className="eyebrow">{t("selectedEntity")}</span>
        <h2>{item.summary.label || item.summary.node_id}</h2>
        <p className="entity-id" dir="ltr">{item.summary.node_id}</p>
        <span className="classification" dir="ltr">{item.summary.classification}</span>
      </header>
      <dl className="explorer-property-list">
        <div><dt>{t("entityType")}</dt><dd dir="ltr">{item.summary.node_type}</dd></div>
        <div><dt>{t("confidence")}</dt><dd dir="ltr">{Math.round(item.summary.confidence * 100)}%</dd></div>
        <div><dt>{t("source")}</dt><dd dir="ltr">{item.source || t("notSpecified")}</dd></div>
        <div><dt>{t("revision")}</dt><dd dir="ltr">#{revision.revision_number}</dd></div>
        <div><dt>{t("createdAt")}</dt><dd dir="ltr">{item.summary.created_at}</dd></div>
        <div><dt>{t("updatedAt")}</dt><dd dir="ltr">{item.summary.updated_at}</dd></div>
      </dl>
      <section>
        <h3>{t("aliases")}</h3>
        <p dir="ltr">{item.aliases.length ? item.aliases.join(", ") : t("noAliases")}</p>
      </section>
      {selectedEdge && (
        <section className="relationship-detail">
          <h3>{t("selectedRelationship")}</h3>
          <dl>
            <div><dt>{t("relationshipId")}</dt><dd dir="ltr">{selectedEdge.id}</dd></div>
            <div><dt>{t("relationshipType")}</dt><dd dir="ltr">{selectedEdge.edgeType}</dd></div>
            <div><dt>{t("direction")}</dt><dd dir="ltr">{selectedEdge.direction}</dd></div>
          </dl>
        </section>
      )}
      <Link className="button button--wide" href={`/entities/${encodeURIComponent(item.summary.node_id)}`}>
        {t("openEntity")} <span className="directional-arrow" aria-hidden="true">→</span>
      </Link>
    </aside>
  );
}

export function KnowledgeGraphExplorer({ initialRootId }: Readonly<{ initialRootId?: string }>) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [graph, setGraph] = useState<GraphState>({ nodes: new Map(), edges: new Map() });
  const [expansions, setExpansions] = useState<Map<string, ExpansionState>>(new Map());
  const [selectedNodeId, setSelectedNodeId] = useState(initialRootId ?? "");
  const [selectedEdgeId, setSelectedEdgeId] = useState<string>();
  const [history, setHistory] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<"graph" | "list">("graph");
  const initialExpansionStarted = useRef(false);

  const root = useQuery({
    queryKey: ["explorer-root", initialRootId],
    queryFn: () => bff.entity(initialRootId as string),
    enabled: Boolean(initialRootId),
    retry: false,
  });
  const pinnedRevision = root.data?.revision_context.revision_number;
  const selectedEntity = useQuery({
    queryKey: ["explorer-entity", selectedNodeId, pinnedRevision],
    queryFn: () => bff.entity(selectedNodeId, pinnedRevision),
    enabled: Boolean(selectedNodeId && pinnedRevision && selectedNodeId !== initialRootId),
    retry: false,
  });

  const expandNode = useCallback(async (nodeId: string, cursor?: string, anchor?: EntitySummary) => {
    if (!pinnedRevision) return;
    setExpansions((current) => new Map(current).set(nodeId, {
      ...current.get(nodeId), loading: true, expanded: current.get(nodeId)?.expanded ?? false, failed: false,
    }));
    try {
      await Promise.resolve();
      if (anchor) {
        setGraph((current) => {
          const nodes = new Map(current.nodes).set(anchor.node_id, anchor);
          return { ...current, nodes };
        });
      }
      const page = await queryClient.fetchQuery({
        queryKey: ["explorer-neighbors", nodeId, cursor ?? "first", pinnedRevision],
        queryFn: () => bff.neighbors(nodeId, cursor, pinnedRevision),
        staleTime: 0,
      });
      setGraph((current) => {
        const nodes = new Map(current.nodes);
        const edges = new Map(current.edges);
        for (const item of page.items) {
          if (!nodes.has(item.entity.node_id) && nodes.size >= MAX_VISIBLE_NODES) continue;
          nodes.set(item.entity.node_id, item.entity);
          edges.set(item.via_edge_id, {
            id: item.via_edge_id,
            anchorId: nodeId,
            neighborId: item.entity.node_id,
            edgeType: item.edge_type,
            direction: item.direction,
            confidence: item.confidence,
          });
        }
        return { nodes, edges };
      });
      setExpansions((current) => new Map(current).set(nodeId, {
        loading: false, expanded: true, pageInfo: page.page_info,
      }));
    } catch (error) {
      if (error instanceof BffError && error.status === 401) {
        void queryClient.invalidateQueries({ queryKey: ["session"] });
      }
      setExpansions((current) => new Map(current).set(nodeId, {
        ...current.get(nodeId), loading: false, expanded: current.get(nodeId)?.expanded ?? false, failed: true,
      }));
    }
  }, [pinnedRevision, queryClient]);

  useEffect(() => {
    if (!root.data || !initialRootId) return;
    if (!initialExpansionStarted.current) {
      initialExpansionStarted.current = true;
      void expandNode(initialRootId, undefined, root.data.item.summary);
    }
  }, [expandNode, initialRootId, root.data]);

  useEffect(() => {
    if (
      (root.error instanceof BffError && root.error.status === 401) ||
      (selectedEntity.error instanceof BffError && selectedEntity.error.status === 401)
    ) {
      void queryClient.invalidateQueries({ queryKey: ["session"] });
    }
  }, [queryClient, root.error, selectedEntity.error]);

  function selectNode(nodeId: string) {
    if (nodeId !== selectedNodeId && selectedNodeId) {
      setHistory((current) => [...current, selectedNodeId]);
    }
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(undefined);
  }

  function goBack() {
    setHistory((current) => {
      const previous = current.at(-1);
      if (previous) setSelectedNodeId(previous);
      return current.slice(0, -1);
    });
    setSelectedEdgeId(undefined);
  }

  if (!initialRootId) {
    return (
      <div className="knowledge-graph-explorer">
        <PageHeader eyebrow={t("knowledgeGraph")} title={t("graphExplorerTitle")} body={t("graphExplorerBody")} />
        <RootDiscovery />
      </div>
    );
  }

  if (root.isPending) return <div className="state-card"><span className="spinner" />{t("loadingGraphRoot")}</div>;
  if (root.error) return <div className="state-card state-card--error" role="alert"><span>!</span><h1>{t("graphUnavailable")}</h1><p>{t("requestFailed")}</p></div>;

  const selectedEdge = selectedEdgeId ? graph.edges.get(selectedEdgeId) : undefined;

  return (
    <div className="knowledge-graph-explorer">
      <PageHeader eyebrow={t("knowledgeGraph")} title={t("graphExplorerTitle")} body={t("graphExplorerBody")} />
      <div className="explorer-toolbar" aria-label={t("graphControls")}>
        <div>
          <span>{t("graphRoot")}</span>
          <strong dir="ltr">{initialRootId}</strong>
        </div>
        <div className="view-switcher" role="group" aria-label={t("viewMode")}>
          <button type="button" aria-pressed={viewMode === "graph"} onClick={() => setViewMode("graph")}>{t("graphView")}</button>
          <button type="button" aria-pressed={viewMode === "list"} onClick={() => setViewMode("list")}>{t("relationshipList")}</button>
        </div>
        <button type="button" disabled={!history.length} onClick={goBack}>{t("previousSelection")}</button>
        <Link href="/knowledge-graph">{t("chooseAnotherRoot")}</Link>
      </div>

      <div className="explorer-layout">
        <section className="explorer-stage" aria-label={t("graphWorkspace")}>
          {viewMode === "graph" ? (
            <GraphCanvas
              rootId={initialRootId}
              graph={graph}
              selectedNodeId={selectedNodeId}
              selectedEdgeId={selectedEdgeId}
              onSelectNode={selectNode}
              onSelectEdge={setSelectedEdgeId}
            />
          ) : (
            <ul className="accessible-graph-list" aria-label={t("relationshipList")}>
              {[...graph.nodes.values()].map((node) => {
                const expansion = expansions.get(node.node_id);
                const relatedEdges = [...graph.edges.values()].filter(
                  (edge) => edge.anchorId === node.node_id || edge.neighborId === node.node_id,
                );
                return (
                  <li key={node.node_id} className={selectedNodeId === node.node_id ? "is-selected" : ""}>
                    <div>
                      <button type="button" onClick={() => selectNode(node.node_id)}>{node.label || node.node_id}</button>
                      <span dir="ltr">{node.node_id}</span>
                      <span className="classification" dir="ltr">{node.classification}</span>
                    </div>
                    <ul>
                      {relatedEdges.map((edge) => (
                        <li key={edge.id}>
                          <button type="button" onClick={() => setSelectedEdgeId(edge.id)}>
                            <bdi dir="ltr">{edge.edgeType}</bdi> · <bdi dir="ltr">{edge.direction}</bdi>
                          </button>
                        </li>
                      ))}
                    </ul>
                    <div className="node-actions">
                      <button type="button" disabled={expansion?.loading || expansion?.expanded} onClick={() => void expandNode(node.node_id)}>
                        {expansion?.loading ? t("expandingNode") : expansion?.expanded ? t("expandedNode") : t("expandNode")}
                      </button>
                      {expansion?.pageInfo?.has_more && expansion.pageInfo.next_cursor && (
                        <button type="button" disabled={expansion.loading} onClick={() => void expandNode(node.node_id, expansion.pageInfo?.next_cursor ?? undefined)}>{t("loadMoreRelationships")}</button>
                      )}
                      <Link href={`/entities/${encodeURIComponent(node.node_id)}`}>{t("openEntity")}</Link>
                    </div>
                    {expansion?.failed && <p className="expansion-error" role="alert">{t("expansionUnavailable")}</p>}
                  </li>
                );
              })}
            </ul>
          )}

          {viewMode === "graph" && selectedNodeId && (
            <div className="graph-selection-actions">
              <button
                type="button"
                disabled={expansions.get(selectedNodeId)?.loading || expansions.get(selectedNodeId)?.expanded}
                onClick={() => void expandNode(selectedNodeId)}
              >
                {expansions.get(selectedNodeId)?.loading ? t("expandingNode") : expansions.get(selectedNodeId)?.expanded ? t("expandedNode") : t("expandSelected")}
              </button>
              {expansions.get(selectedNodeId)?.pageInfo?.has_more && expansions.get(selectedNodeId)?.pageInfo?.next_cursor && (
                <button type="button" onClick={() => void expandNode(selectedNodeId, expansions.get(selectedNodeId)?.pageInfo?.next_cursor ?? undefined)}>{t("loadMoreRelationships")}</button>
              )}
              {expansions.get(selectedNodeId)?.failed && <span role="alert">{t("expansionUnavailable")}</span>}
            </div>
          )}
          {graph.nodes.size >= MAX_VISIBLE_NODES && <p className="availability-note">{t("graphViewLimit")}</p>}
        </section>
        <EntityDetailPanel result={selectedNodeId === initialRootId ? root.data : selectedEntity.data} loading={selectedNodeId === initialRootId ? false : selectedEntity.isFetching} selectedEdge={selectedEdge} />
      </div>
    </div>
  );
}
