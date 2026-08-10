"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useState } from "react";

import { useI18n } from "@/i18n/i18n";
import { BffError, bff } from "@/lib/bff";
import type { EntityResponse } from "@/lib/contracts";
import { PageHeader } from "./ui";

const PILOT_ENTITY = "pilot-entity-001";

function EntityDetails({ result }: Readonly<{ result: EntityResponse }>) {
  const { t } = useI18n();
  const { item, revision_context: revision } = result;
  const metadata = Object.entries(item.metadata);
  return <article className="entity-panel" aria-live="polite"><header className="entity-heading"><div><span className="eyebrow">{t("entityType")}: <bdi>{item.summary.node_type}</bdi></span><h2>{item.summary.label || item.summary.node_id}</h2><p className="entity-id" dir="ltr">{item.summary.node_id}</p></div><span className="classification" dir="ltr">{item.summary.classification}</span></header>
    <div className="metric-grid"><div><span>{t("confidence")}</span><strong dir="ltr">{Math.round(item.summary.confidence * 100)}%</strong></div><div><span>{t("revision")}</span><strong dir="ltr">#{revision.revision_number}</strong></div><div><span>{t("source")}</span><strong dir="ltr">{item.source || t("notSpecified")}</strong></div></div>
    <section className="detail-section"><h3>{t("properties")}</h3>{metadata.length ? <dl className="property-list">{metadata.map(([key, value]) => <div key={key}><dt dir="ltr">{key}</dt><dd dir="ltr">{value}</dd></div>)}</dl> : <p className="empty-copy">{t("noProperties")}</p>}</section>
    <section className="detail-section two-column"><div><h3>{t("aliases")}</h3><p dir="ltr">{item.aliases.length ? item.aliases.join(", ") : t("noAliases")}</p></div><div><h3>{t("evidenceLabel")}</h3><p><bdi>{item.evidence.length}</bdi> {t(item.evidence.length === 1 ? "linkedRecord" : "linkedRecords")}</p></div></section>
  </article>;
}

export function EntityWorkspace() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [draftId, setDraftId] = useState(PILOT_ENTITY);
  const [entityId, setEntityId] = useState<string | null>(null);
  const entity = useQuery({ queryKey: ["entity", entityId], queryFn: () => bff.entity(entityId as string), enabled: entityId !== null });
  const expired = entity.error instanceof BffError && entity.error.status === 401;
  useEffect(() => { if (expired) void queryClient.invalidateQueries({ queryKey: ["session"] }); }, [expired, queryClient]);
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const normalized = draftId.trim(); if (normalized) setEntityId(normalized); }
  return <div><PageHeader eyebrow={t("knowledgeGraph")} title={t("entityWorkspace")} body={t("entityWorkspaceBody")} />
    <form className="lookup" onSubmit={submit}><label htmlFor="entity-id">{t("entityId")}</label><div className="lookup-row"><input id="entity-id" dir="ltr" value={draftId} onChange={(event) => setDraftId(event.target.value)} /><button type="submit" disabled={entity.isFetching}>{t("explore")}</button></div><span className="hint">{t("pilotEntity")}: <bdi>{PILOT_ENTITY}</bdi></span></form>
    <section className="results" aria-busy={entity.isFetching}>{entity.isFetching && <div className="state-card"><span className="spinner" />{t("loadingEntity")}</div>}{!entityId && !entity.isFetching && <div className="state-card state-card--empty"><span>⌁</span><h2>{t("readyTitle")}</h2><p>{t("readyBody")}</p></div>}{entity.error && !expired && <div className="state-card state-card--error" role="alert"><span>!</span><h2>{t("unavailableTitle")}</h2><p>{entity.error instanceof BffError && entity.error.status === 404 ? t("notFound") : t("requestFailed")}</p></div>}{entity.data && <EntityDetails result={entity.data} />}</section>
  </div>;
}
