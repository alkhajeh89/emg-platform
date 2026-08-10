"use client";

import { useI18n, type MessageKey } from "@/i18n/i18n";
import { ActionLink, EmptyState, PageHeader } from "./ui";

export function PlannedWorkspace({ title }: Readonly<{ title: MessageKey }>) {
  const { t } = useI18n();
  return <div><PageHeader eyebrow={t("plannedWorkspace")} title={t(title)} body={t("plannedBody")} /><EmptyState title={`${t(title)} · ${t("planned")}`} body={t("plannedBody")} /><div className="page-actions"><ActionLink href="/dashboard" secondary>{t("returnDashboard")}</ActionLink></div></div>;
}
