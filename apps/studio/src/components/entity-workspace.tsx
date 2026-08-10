"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useI18n } from "@/i18n/i18n";
import { BffError, bff } from "@/lib/bff";
import type { EntityResponse, NeighborResponse } from "@/lib/contracts";
import { PageHeader } from "./ui";

const PILOT_ENTITY = "pilot-entity-001";

function Evidence({ result }: Readonly<{ result: EntityResponse }>) {
  const { t } = useI18n();
  if (!result.item.evidence.length) return <p className="empty-copy">{t("noEvidence")}</p>;
  return <ul className="record-list">{result.item.evidence.map((item) => <li key={item.evidence_id}><strong dir="ltr">{item.evidence_id}</strong><dl><div><dt>{t("source")}</dt><dd dir="ltr">{item.source}</dd></div><div><dt>{t("locator")}</dt><dd dir="ltr">{item.locator}</dd></div><div><dt>{t("capturedAt")}</dt><dd dir="ltr">{item.captured_at}</dd></div></dl>{item.description && <p>{item.description}</p>}</li>)}</ul>;
}

function Histories({ result }: Readonly<{ result: EntityResponse }>) {
  const { t } = useI18n();
  if (!result.item.histories.length) return <p className="empty-copy">{t("noHistory")}</p>;
  return <div className="history-list">{result.item.histories.map((history) => <section key={history.attribute}><h4 dir="ltr">{history.attribute}</h4><ul>{history.facts.map((fact, index) => <li key={`${fact.recorded_at}-${index}`}><span dir="ltr">{fact.value}</span><small dir="ltr">{fact.validity.valid_from} — {fact.validity.valid_until ?? t("current")}</small></li>)}</ul></section>)}</div>;
}

function Relationships({ result }: Readonly<{ result: NeighborResponse | undefined }>) {
  const { t } = useI18n();
  if (!result) return null;
  if (!result.items.length) return <p className="empty-copy">{t("noRelationships")}</p>;
  return <div><ul className="relationship-list">{result.items.map((item) => <li key={item.via_edge_id}><div><strong>{item.entity.label || item.entity.node_id}</strong><span dir="ltr">{item.edge_type} · {item.direction}</span></div><Link href={`/entities/${encodeURIComponent(item.entity.node_id)}`} dir="ltr">{item.entity.node_id}</Link></li>)}</ul>{result.page_info.has_more && <p className="availability-note">{t("moreRelationshipsAvailable")}</p>}</div>;
}

function EntityDetails({ result, relationships }: Readonly<{ result: EntityResponse; relationships?: NeighborResponse }>) {
  const { t } = useI18n();
  const { item, revision_context: revision } = result;
  const metadata = Object.entries(item.metadata);
  return <article className="entity-panel" aria-live="polite"><header className="entity-heading"><div><span className="eyebrow">{t("entityType")}: <bdi>{item.summary.node_type}</bdi></span><h2>{item.summary.label || item.summary.node_id}</h2><p className="entity-id" dir="ltr">{item.summary.node_id}</p><Link className="graph-entry-link" href={`/knowledge-graph/${encodeURIComponent(item.summary.node_id)}`}>{t("exploreInGraph")}</Link></div><span className="classification" dir="ltr">{item.summary.classification}</span></header>
    <div className="metric-grid"><div><span>{t("confidence")}</span><strong dir="ltr">{Math.round(item.summary.confidence * 100)}%</strong></div><div><span>{t("revision")}</span><strong dir="ltr">#{revision.revision_number}</strong></div><div><span>{t("source")}</span><strong dir="ltr">{item.source || t("notSpecified")}</strong></div></div>
    <section className="detail-section"><h3>{t("identity")}</h3><dl className="property-list"><div><dt>{t("createdAt")}</dt><dd dir="ltr">{item.summary.created_at}</dd></div><div><dt>{t("updatedAt")}</dt><dd dir="ltr">{item.summary.updated_at}</dd></div><div><dt>{t("revisionCommitted")}</dt><dd dir="ltr">{revision.committed_at}</dd></div></dl></section>
    <section className="detail-section"><h3>{t("properties")}</h3>{metadata.length ? <dl className="property-list">{metadata.map(([key, value]) => <div key={key}><dt dir="ltr">{key}</dt><dd dir="ltr">{value}</dd></div>)}</dl> : <p className="empty-copy">{t("noProperties")}</p>}</section>
    <section className="detail-section"><h3>{t("aliases")}</h3><p dir="ltr">{item.aliases.length ? item.aliases.join(", ") : t("noAliases")}</p></section>
    <section className="detail-section"><h3>{t("evidenceLabel")}</h3><Evidence result={result} /></section>
    <section className="detail-section"><h3>{t("relationships")}</h3><Relationships result={relationships} /></section>
    <section className="detail-section"><h3>{t("history")}</h3><Histories result={result} /></section>
  </article>;
}

export function EntityWorkspace({ initialEntityId }: Readonly<{ initialEntityId?: string }>) {
  const { t } = useI18n();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [draftId, setDraftId] = useState(initialEntityId ?? "");
  const entityId = initialEntityId ?? null;
  const entity = useQuery({ queryKey: ["entity", entityId], queryFn: () => bff.entity(entityId as string), enabled: entityId !== null, retry: false });
  const neighbors = useQuery({ queryKey: ["neighbors", entityId], queryFn: () => bff.neighbors(entityId as string), enabled: Boolean(entity.data), retry: false });
  const expired = (entity.error instanceof BffError && entity.error.status === 401) || (neighbors.error instanceof BffError && neighbors.error.status === 401);
  useEffect(() => { if (expired) void queryClient.invalidateQueries({ queryKey: ["session"] }); }, [expired, queryClient]);
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const normalized = draftId.trim(); if (normalized) router.push(`/entities/${encodeURIComponent(normalized)}`); }
  return <div><PageHeader eyebrow={t("knowledgeGraph")} title={t("entityWorkspace")} body={t("entityWorkspaceBody")} />
    <form className="lookup" onSubmit={submit}><label htmlFor="entity-id">{t("entityId")}</label><div className="lookup-row"><input id="entity-id" dir="ltr" value={draftId} onChange={(event) => setDraftId(event.target.value)} placeholder={PILOT_ENTITY} /><button type="submit">{t("explore")}</button></div><span className="hint">{t("canonicalLookupHint")}</span></form>
    <section className="results" aria-busy={entity.isFetching}>{entity.isFetching && <div className="state-card"><span className="spinner" />{t("loadingEntity")}</div>}{!entityId && <div className="state-card state-card--empty"><span>⌁</span><h2>{t("readyTitle")}</h2><p>{t("readyBody")}</p></div>}{entity.error && !expired && <div className="state-card state-card--error" role="alert"><span>!</span><h2>{t("unavailableTitle")}</h2><p>{entity.error instanceof BffError && entity.error.status === 404 ? t("notFound") : t("requestFailed")}</p></div>}{entity.data && <><EntityDetails result={entity.data} relationships={neighbors.data} />{neighbors.error && !(neighbors.error instanceof BffError && neighbors.error.status === 401) && <p className="availability-note" role="status">{t("relationshipsUnavailable")}</p>}</>}</section>
  </div>;
}
