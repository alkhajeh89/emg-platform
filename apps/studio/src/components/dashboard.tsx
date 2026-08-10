"use client";

import { useI18n } from "@/i18n/i18n";
import { ActionLink, EmptyState, PageHeader, SectionHeader, StatusMark } from "./ui";

export function Dashboard() {
  const { t } = useI18n();
  return <div className="dashboard-page">
    <PageHeader eyebrow={t("dashboardEyebrow")} title={t("dashboardTitle")} body={t("dashboardBody")} />
    <section aria-labelledby="overview-heading"><SectionHeader id="overview-heading" title={t("workspaceOverview")} label={t("backendData")} />
      <div className="card-grid card-grid--two">
        <article className="card"><div className="card-title"><StatusMark /><h3>{t("platformStatus")}</h3></div><strong>{t("platformAvailable")}</strong><p>{t("platformStatusBody")}</p><span className="data-label">{t("backendData")}</span></article>
        <article className="card"><div className="card-title"><StatusMark /><h3>{t("securityContext")}</h3></div><p>{t("securityContextBody")}</p><span className="data-label">{t("backendData")}</span></article>
      </div>
    </section>
    <section aria-labelledby="actions-heading"><SectionHeader id="actions-heading" title={t("quickActions")} label={t("staticNavigation")} />
      <div className="action-grid"><ActionLink href="/entities">{t("explorePilot")}</ActionLink><ActionLink href="/search" secondary>{t("openSearch")}</ActionLink><ActionLink href="/knowledge-graph" secondary>{t("viewKnowledgeGraph")}</ActionLink></div>
    </section>
    <div className="dashboard-columns">
      <section aria-labelledby="activity-heading"><SectionHeader id="activity-heading" title={t("recentActivity")} label={t("intentionallyUnavailable")} /><EmptyState title={t("noActivityTitle")} body={t("noActivityBody")} /></section>
      <section aria-labelledby="shortcuts-heading"><SectionHeader id="shortcuts-heading" title={t("workspaceShortcuts")} label={t("staticNavigation")} />
        <div className="shortcut-list">
          <ActionLink href="/entities" secondary>{t("openEntities")} · {t("available")}</ActionLink>
          <ActionLink href="/evidence" secondary>{t("evidence")} · {t("planned")}</ActionLink>
          <ActionLink href="/timeline" secondary>{t("timeline")} · {t("planned")}</ActionLink>
          <ActionLink href="/decisions" secondary>{t("decisions")} · {t("planned")}</ActionLink>
        </div>
      </section>
    </div>
  </div>;
}
