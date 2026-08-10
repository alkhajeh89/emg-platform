"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";

import { useI18n, type MessageKey } from "@/i18n/i18n";
import { BffError, bff } from "@/lib/bff";
import type {
  GovernedSearchResponse,
  SearchMatchKind,
} from "@/lib/contracts";
import { useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "./ui";

type SearchPhase =
  | "initial"
  | "typing"
  | "loading"
  | "results"
  | "empty"
  | "loading-more"
  | "continuation-invalid"
  | "validation-error"
  | "backend-error"
  | "session-expired";

interface SearchView {
  phase: SearchPhase;
  items: GovernedSearchResponse["items"];
  pageInfo?: GovernedSearchResponse["page_info"];
  revision?: GovernedSearchResponse["revision_context"];
}

const INITIAL_VIEW: SearchView = { phase: "initial", items: [] };
const INVALID_CONTINUATION = "KNOWLEDGE_GRAPH_INVALID_SEARCH_CONTINUATION";

const matchKindMessages: Record<SearchMatchKind, MessageKey> = {
  ID_EXACT: "matchIdExact",
  LABEL_EXACT: "matchLabelExact",
  ALIAS_EXACT: "matchAliasExact",
  ID_PREFIX: "matchIdPrefix",
  LABEL_PREFIX: "matchLabelPrefix",
  ALIAS_PREFIX: "matchAliasPrefix",
};

function deduplicate(
  items: GovernedSearchResponse["items"],
): GovernedSearchResponse["items"] {
  const unique = new Map<string, GovernedSearchResponse["items"][number]>();
  for (const item of items) {
    if (!unique.has(item.entity.node_id)) unique.set(item.entity.node_id, item);
  }
  return [...unique.values()];
}

export function SearchWorkspace() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [view, setView] = useState<SearchView>(INITIAL_VIEW);
  const activeRequest = useRef<AbortController | null>(null);
  const requestSequence = useRef(0);

  useEffect(() => () => activeRequest.current?.abort(), []);

  function cancelActiveRequest() {
    requestSequence.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
  }

  function changeDraft(value: string) {
    setDraft(value);
    if (view.phase !== "initial" && view.phase !== "typing") {
      cancelActiveRequest();
      setSubmittedQuery("");
      setView({ phase: "typing", items: [] });
    } else if (view.phase === "initial") {
      setView({ phase: "typing", items: [] });
    }
  }

  async function runSearch(
    query: string,
    cursor?: string,
    existingItems: GovernedSearchResponse["items"] = [],
  ) {
    cancelActiveRequest();
    const controller = new AbortController();
    activeRequest.current = controller;
    const sequence = requestSequence.current;
    setView((current) => ({
      ...current,
      phase: cursor ? "loading-more" : "loading",
      items: cursor ? existingItems : [],
      pageInfo: cursor ? current.pageInfo : undefined,
      revision: cursor ? current.revision : undefined,
    }));

    try {
      const result = await bff.search(
        { q: query, limit: 20, ...(cursor ? { cursor } : {}) },
        controller.signal,
      );
      if (sequence !== requestSequence.current) return;
      const items = deduplicate([...existingItems, ...result.items]);
      setView({
        phase: items.length ? "results" : "empty",
        items,
        pageInfo: result.page_info,
        revision: result.revision_context,
      });
    } catch (error) {
      if (sequence !== requestSequence.current || (error instanceof DOMException && error.name === "AbortError")) return;
      if (error instanceof BffError && error.status === 401) {
        setView({ phase: "session-expired", items: [] });
        void queryClient.invalidateQueries({ queryKey: ["session"] });
      } else if (
        cursor &&
        error instanceof BffError &&
        error.errorCode === INVALID_CONTINUATION
      ) {
        setView((current) => ({ ...current, phase: "continuation-invalid" }));
      } else if (error instanceof BffError && error.status === 400) {
        setView({ phase: "validation-error", items: [] });
      } else {
        setView({ phase: "backend-error", items: [] });
      }
    } finally {
      if (sequence === requestSequence.current) activeRequest.current = null;
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.trim()) {
      cancelActiveRequest();
      setSubmittedQuery("");
      setView({ phase: "validation-error", items: [] });
      return;
    }
    setSubmittedQuery(draft);
    void runSearch(draft);
  }

  function loadMore() {
    const cursor = view.pageInfo?.next_cursor;
    if (submittedQuery && view.pageInfo?.has_more && cursor) {
      void runSearch(submittedQuery, cursor, view.items);
    }
  }

  function restartSearch() {
    if (submittedQuery) void runSearch(submittedQuery);
  }

  const loading = view.phase === "loading" || view.phase === "loading-more";

  return (
    <div className="search-workspace">
      <PageHeader
        eyebrow={t("knowledgeGraph")}
        title={t("searchTitle")}
        body={t("searchBody")}
      />
      <form className="lookup search-lookup" role="search" onSubmit={submit}>
        <label htmlFor="entity-search">{t("searchQueryLabel")}</label>
        <div className="lookup-row">
          <input
            id="entity-search"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            value={draft}
            onChange={(event) => changeDraft(event.target.value)}
            placeholder={t("searchQueryPlaceholder")}
          />
          <button type="submit" disabled={loading}>
            {t("searchAction")}
          </button>
        </div>
        <span className="hint">{t("governedSearchHint")}</span>
      </form>

      <section className="results search-results" aria-busy={loading}>
        <p className="sr-only" role="status" aria-live="polite">
          {view.phase === "loading"
            ? t("searching")
            : view.phase === "loading-more"
              ? t("loadingMore")
              : view.phase === "results"
                ? t("resultsAvailable")
                : ""}
        </p>

        {view.phase === "initial" && (
          <div className="state-card state-card--empty">
            <span aria-hidden="true">⌁</span>
            <h2>{t("searchReadyTitle")}</h2>
            <p>{t("searchReadyBody")}</p>
          </div>
        )}
        {view.phase === "typing" && (
          <div className="state-card state-card--empty">
            <span aria-hidden="true">⌁</span>
            <h2>{t("searchTypingTitle")}</h2>
            <p>{t("searchTypingBody")}</p>
          </div>
        )}
        {view.phase === "loading" && (
          <div className="state-card">
            <span className="spinner" aria-hidden="true" />
            {t("searching")}
          </div>
        )}
        {view.phase === "empty" && (
          <div className="state-card state-card--empty">
            <span aria-hidden="true">⌁</span>
            <h2>{t("noResultsTitle")}</h2>
            <p>{t("noResultsBody")}</p>
          </div>
        )}
        {(view.phase === "validation-error" || view.phase === "backend-error") && (
          <div className="state-card state-card--error" role="alert">
            <span aria-hidden="true">!</span>
            <h2>
              {view.phase === "validation-error"
                ? t("invalidSearchTitle")
                : t("searchUnavailable")}
            </h2>
            <p>
              {view.phase === "validation-error"
                ? t("invalidSearchBody")
                : t("requestFailed")}
            </p>
          </div>
        )}
        {view.phase === "session-expired" && (
          <div className="state-card state-card--error" role="alert">
            <span aria-hidden="true">!</span>
            <h2>{t("sessionExpiredTitle")}</h2>
            <p>{t("sessionExpiredBody")}</p>
          </div>
        )}

        {view.items.length > 0 && (
          <div className="search-result-set">
            {view.revision && (
              <div className="search-revision" role="status">
                <span>{t("revisionContext")}</span>
                <strong dir="ltr">#{view.revision.revision_number}</strong>
              </div>
            )}
            <ul className="search-result-list" aria-label={t("authorizedResults") }>
              {view.items.map((item) => (
                <li key={item.entity.node_id}>
                  <article className="search-result">
                    <div className="search-result__main">
                      <div className="search-result__meta">
                        <span className="match-kind">{t(matchKindMessages[item.match_kind])}</span>
                        <span className="classification" dir="ltr">
                          {item.entity.classification}
                        </span>
                      </div>
                      <h2>{item.entity.label || item.entity.node_id}</h2>
                      <p className="entity-id" dir="ltr">{item.entity.node_id}</p>
                      <p className="entity-type">
                        {t("entityType")}: <bdi dir="ltr">{item.entity.node_type}</bdi>
                      </p>
                    </div>
                    <Link
                      className="button button--secondary"
                      href={`/entities/${encodeURIComponent(item.entity.node_id)}`}
                    >
                      {t("openEntity")}
                    </Link>
                    <Link
                      className="button"
                      href={`/knowledge-graph/${encodeURIComponent(item.entity.node_id)}`}
                    >
                      {t("exploreInGraph")}
                    </Link>
                  </article>
                </li>
              ))}
            </ul>

            {view.phase === "continuation-invalid" ? (
              <div className="continuation-state" role="alert">
                <div>
                  <strong>{t("continuationUnavailableTitle")}</strong>
                  <p>{t("continuationUnavailableBody")}</p>
                </div>
                <button type="button" onClick={restartSearch}>{t("restartSearch")}</button>
              </div>
            ) : view.pageInfo?.has_more && view.pageInfo.next_cursor ? (
              <div className="load-more-row">
                <button type="button" onClick={loadMore} disabled={view.phase === "loading-more"}>
                  {view.phase === "loading-more" ? t("loadingMore") : t("loadMore")}
                </button>
              </div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
