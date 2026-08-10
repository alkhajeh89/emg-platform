"use client";

import { useI18n } from "@/i18n/i18n";
import { bff } from "@/lib/bff";
import { StatusMark } from "./ui";

export function LoginPanel() {
  const { t } = useI18n();
  return <main className="center-stage"><section className="login-card" aria-labelledby="login-heading">
    <span className="eyebrow">{t("secureWorkspace")}</span><h1 id="login-heading">{t("loginTitle")}</h1>
    <p>{t("loginBody")}</p><a className="button button--wide" href={bff.loginUrl}>{t("loginAction")}<span className="directional-arrow" aria-hidden="true">→</span></a>
    <div className="trust-note"><StatusMark />{t("protectedBy")}</div>
  </section></main>;
}
