"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { useI18n, type MessageKey } from "@/i18n/i18n";
import { BffError, bff } from "@/lib/bff";
import { LoginPanel } from "./login-panel";
import { StatusMark } from "./ui";

const navigation: Array<{ href: string; label: MessageKey; mark: string }> = [
  { href: "/dashboard", label: "dashboard", mark: "D" }, { href: "/search", label: "search", mark: "S" },
  { href: "/knowledge-graph", label: "knowledgeGraph", mark: "K" }, { href: "/entities", label: "entities", mark: "E" },
  { href: "/evidence", label: "evidence", mark: "V" }, { href: "/timeline", label: "timeline", mark: "T" },
  { href: "/decisions", label: "decisions", mark: "C" },
];

function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();
  return <div className="language-switcher" aria-label={t("language")}>
    <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")} lang="en">{t("english")}</button>
    <span aria-hidden="true">|</span>
    <button type="button" aria-pressed={locale === "ar"} onClick={() => setLocale("ar")} lang="ar">{t("arabic")}</button>
  </div>;
}

export function ApplicationShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const { t } = useI18n();
  const pathname = usePathname();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [logoutError, setLogoutError] = useState(false);
  const session = useQuery({ queryKey: ["session"], queryFn: bff.session });
  const unauthorized = session.error instanceof BffError && session.error.status === 401;
  const current = navigation.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))?.label ?? "dashboard";

  async function logout() {
    setLogoutError(false);
    try { await bff.logout(); await session.refetch(); } catch { setLogoutError(true); }
  }
  function search(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const data = new FormData(event.currentTarget); const query = String(data.get("q") ?? "").trim(); router.push(query ? `/search?q=${encodeURIComponent(query)}` : "/search"); }

  if (session.isPending) return <main className="center-stage"><div className="state-card" aria-live="polite"><span className="spinner" />{t("checkingSession")}</div></main>;
  if (unauthorized) return <LoginPanel />;
  if (session.error) return <main className="center-stage"><div className="state-card state-card--error" role="alert"><span>!</span><h1>{t("studioUnavailable")}</h1><p>{t("sessionUnavailable")}</p><button type="button" onClick={() => session.refetch()}>{t("retry")}</button></div></main>;

  return <div className="enterprise-shell">
    <a className="skip-link" href="#main-content">{t("skipContent")}</a>
    <aside className={`sidebar ${drawerOpen ? "sidebar--open" : ""}`} aria-label={t("primaryNavigation")}>
      <div className="sidebar-brand"><Link href="/dashboard" aria-label={t("brandHome")}><span className="brand-mark">E</span><span>{t("brand")}</span></Link><button type="button" className="drawer-close" onClick={() => setDrawerOpen(false)} aria-label={t("closeNavigation")}>×</button></div>
      <nav><ul>{navigation.map((item) => { const active = pathname === item.href || pathname.startsWith(`${item.href}/`); return <li key={item.href}><Link href={item.href} aria-current={active ? "page" : undefined} onClick={() => setDrawerOpen(false)}><span className="nav-mark" aria-hidden="true">{item.mark}</span>{t(item.label)}</Link></li>; })}</ul></nav>
      <div className="sidebar-boundary"><StatusMark /><span>{t("boundary")}</span></div>
    </aside>
    {drawerOpen && <button type="button" className="drawer-scrim" onClick={() => setDrawerOpen(false)} aria-label={t("closeNavigation")} />}
    <div className="shell-main">
      <header className="application-bar">
        <button type="button" className="menu-button" onClick={() => setDrawerOpen(true)} aria-label={t("openNavigation")} aria-expanded={drawerOpen}>☰</button>
        <div className="section-indicator"><span>{t("currentSection")}</span><strong>{t(current)}</strong></div>
        <form className="global-search" role="search" onSubmit={search}><label className="sr-only" htmlFor="global-search">{t("globalSearch")}</label><input id="global-search" name="q" dir="ltr" placeholder={t("searchPlaceholder")} /><button type="submit" aria-label={t("searchAction")}>⌕</button></form>
        <div className="application-actions"><LanguageSwitcher /><div className="session-area"><span><StatusMark />{t("authenticated")}</span><button type="button" onClick={logout}>{t("logout")}</button></div></div>
      </header>
      <main id="main-content" className="page-content" tabIndex={-1}>{children}</main>
      <footer><span>{t("platform")}</span><span>{t("boundary")}</span></footer>
    </div>
    {logoutError && <div className="toast" role="alert">{t("logoutFailed")}</div>}
  </div>;
}
