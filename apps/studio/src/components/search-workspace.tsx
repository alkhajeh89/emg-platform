"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useI18n } from "@/i18n/i18n";
import { BffError, bff } from "@/lib/bff";
import { PageHeader } from "./ui";

export function SearchWorkspace({ initialQuery = "" }: Readonly<{ initialQuery?: string }>) {
  const { t } = useI18n();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(initialQuery);
  const [query, setQuery] = useState(initialQuery.trim());
  const result = useQuery({ queryKey: ["entity-search", query], queryFn: () => bff.entity(query), enabled: Boolean(query), retry: false });
  const expired = result.error instanceof BffError && result.error.status === 401;
  useEffect(() => { if (expired) void queryClient.invalidateQueries({ queryKey: ["session"] }); }, [expired, queryClient]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = draft.trim();
    if (!normalized) return;
    setQuery(normalized);
    router.replace(`/search?q=${encodeURIComponent(normalized)}`);
  }

  return <div><PageHeader eyebrow={t("knowledgeGraph")} title={t("searchTitle")} body={t("searchBody")} />
    <form className="lookup search-lookup" role="search" onSubmit={submit}>
      <label htmlFor="entity-search">{t("canonicalId")}</label>
      <div className="lookup-row"><input id="entity-search" dir="ltr" autoComplete="off" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={t("canonicalIdPlaceholder")} /><button type="submit" disabled={result.isFetching}>{t("lookup")}</button></div>
      <span className="hint">{t("exactLookupOnly")}</span>
    </form>
    <section className="results" aria-busy={result.isFetching} aria-live="polite">
      {result.isFetching && <div className="state-card"><span className="spinner" />{t("searching")}</div>}
      {!query && !result.isFetching && <div className="state-card state-card--empty"><span>⌁</span><h2>{t("searchReadyTitle")}</h2><p>{t("searchReadyBody")}</p></div>}
      {result.error && !expired && <div className="state-card state-card--error" role="alert"><span>!</span><h2>{result.error instanceof BffError && result.error.status === 404 ? t("noResultsTitle") : t("searchUnavailable")}</h2><p>{result.error instanceof BffError && result.error.status === 404 ? t("noResultsBody") : t("requestFailed")}</p></div>}
      {result.data && <article className="search-result"><div><span className="eyebrow">{t("entityType")}: <bdi>{result.data.item.summary.node_type}</bdi></span><h2>{result.data.item.summary.label || result.data.item.summary.node_id}</h2><p className="entity-id" dir="ltr">{result.data.item.summary.node_id}</p></div><span className="classification" dir="ltr">{result.data.item.summary.classification}</span><Link className="button" href={`/entities/${encodeURIComponent(result.data.item.summary.node_id)}`}>{t("openEntity")}</Link></article>}
    </section>
  </div>;
}
