"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { FormEvent, useState } from "react";

import { useI18n } from "@/i18n/i18n";
import { BffError, bff } from "@/lib/bff";
import type { EntityResponse } from "@/lib/contracts";

const PILOT_ENTITY = "pilot-entity-001";

function StatusMark() {
  return <span className="status-mark status-mark--online" aria-hidden="true" />;
}

function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();
  return (
    <div className="language-switcher" aria-label={t("language")}>
      <button aria-pressed={locale === "en"} onClick={() => setLocale("en")} lang="en">{t("english")}</button>
      <span aria-hidden="true">|</span>
      <button aria-pressed={locale === "ar"} onClick={() => setLocale("ar")} lang="ar">{t("arabic")}</button>
    </div>
  );
}

function LoginPanel() {
  const { t } = useI18n();
  return (
    <main className="center-stage">
      <section className="login-card" aria-labelledby="login-heading">
        <span className="eyebrow">{t("secureWorkspace")}</span>
        <h1 id="login-heading">{t("loginTitle")}</h1>
        <p>{t("loginBody")}</p>
        <a className="primary-button" href={bff.loginUrl}>
          {t("loginAction")} <span className="directional-arrow" aria-hidden="true">→</span>
        </a>
        <div className="trust-note"><StatusMark /> {t("protectedBy")}</div>
      </section>
    </main>
  );
}

function EntityDetails({ result }: Readonly<{ result: EntityResponse }>) {
  const { t } = useI18n();
  const { item, revision_context: revision } = result;
  const metadata = Object.entries(item.metadata);
  return (
    <article className="entity-panel" aria-live="polite">
      <header className="entity-heading">
        <div>
          <span className="eyebrow">{t("entityType")}: {item.summary.node_type}</span>
          <h2>{item.summary.label || item.summary.node_id}</h2>
          <p className="entity-id" dir="ltr">{item.summary.node_id}</p>
        </div>
        <span className="classification" dir="ltr">{item.summary.classification}</span>
      </header>
      <div className="metric-grid">
        <div><span>{t("confidence")}</span><strong dir="ltr">{Math.round(item.summary.confidence * 100)}%</strong></div>
        <div><span>{t("revision")}</span><strong dir="ltr">#{revision.revision_number}</strong></div>
        <div><span>{t("source")}</span><strong>{item.source || t("notSpecified")}</strong></div>
      </div>
      <section className="detail-section">
        <h3>{t("properties")}</h3>
        {metadata.length ? <dl className="property-list">{metadata.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl> : <p className="empty-copy">{t("noProperties")}</p>}
      </section>
      <section className="detail-section two-column">
        <div><h3>{t("aliases")}</h3><p>{item.aliases.length ? item.aliases.join(", ") : t("noAliases")}</p></div>
        <div><h3>{t("evidence")}</h3><p>{item.evidence.length} {t(item.evidence.length === 1 ? "linkedRecord" : "linkedRecords")}</p></div>
      </section>
    </article>
  );
}

function Workspace() {
  const { t } = useI18n();
  const [draftId, setDraftId] = useState(PILOT_ENTITY);
  const [entityId, setEntityId] = useState<string | null>(null);
  const entity = useQuery({ queryKey: ["entity", entityId], queryFn: () => bff.entity(entityId as string), enabled: entityId !== null });
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const normalized = draftId.trim(); if (normalized) setEntityId(normalized); }
  if (entity.error instanceof BffError && entity.error.status === 401) return <LoginPanel />;
  return (
    <main className="workspace">
      <section className="hero"><span className="eyebrow">{t("knowledgeGraph")}</span><h1>{t("heroLine1")}<br /><em>{t("heroLine2")}</em></h1><p>{t("heroBody")}</p></section>
      <form className="lookup" onSubmit={submit}>
        <label htmlFor="entity-id">{t("entityId")}</label>
        <div className="lookup-row"><input id="entity-id" dir="ltr" value={draftId} onChange={(event) => setDraftId(event.target.value)} /><button type="submit" disabled={entity.isFetching}>{t("explore")}</button></div>
        <span className="hint">{t("pilotEntity")}: <bdi>{PILOT_ENTITY}</bdi></span>
      </form>
      <section className="results" aria-busy={entity.isFetching}>
        {entity.isFetching && <div className="state-card"><span className="spinner" />{t("loadingEntity")}</div>}
        {!entityId && !entity.isFetching && <div className="state-card state-card--empty"><span>⌁</span><h2>{t("readyTitle")}</h2><p>{t("readyBody")}</p></div>}
        {entity.error && <div className="state-card state-card--error" role="alert"><span>!</span><h2>{t("unavailableTitle")}</h2><p>{entity.error instanceof BffError && entity.error.status === 404 ? t("notFound") : t("requestFailed")}</p></div>}
        {entity.data && <EntityDetails result={entity.data} />}
      </section>
    </main>
  );
}

export function Studio() {
  const { t } = useI18n();
  const session = useQuery({ queryKey: ["session"], queryFn: bff.session });
  const [logoutError, setLogoutError] = useState(false);
  async function logout() {
    setLogoutError(false);
    try { await bff.logout(); await session.refetch(); } catch { setLogoutError(true); }
  }
  const unauthorized = session.error instanceof BffError && session.error.status === 401;
  // React Query deliberately retains the last successful value when a
  // refetch fails. A confirmed logout followed by the expected 401 must not
  // let that stale cache keep the authenticated workspace visible.
  const authenticated = session.data?.authenticated === true && !unauthorized;
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" href="/" aria-label={t("brandHome")}><span className="brand-mark">E</span><span>{t("brand")}</span></Link>
        <div className="topbar-actions"><LanguageSwitcher /><div className="session-state">{authenticated && <><span><StatusMark />{t("authenticated")}</span><button className="text-button" onClick={logout}>{t("logout")}</button></>}</div></div>
      </header>
      {session.isPending && <main className="center-stage"><div className="state-card" aria-live="polite"><span className="spinner" />{t("checkingSession")}</div></main>}
      {unauthorized && <LoginPanel />}
      {session.error && !unauthorized && <main className="center-stage"><div className="state-card state-card--error" role="alert"><span>!</span><h1>{t("studioUnavailable")}</h1><p>{t("sessionUnavailable")}</p><button onClick={() => session.refetch()}>{t("retry")}</button></div></main>}
      {authenticated && <Workspace />}
      {logoutError && <div className="toast" role="alert">{t("logoutFailed")}</div>}
      <footer><span>{t("platform")}</span><span>{t("boundary")}</span></footer>
    </div>
  );
}
