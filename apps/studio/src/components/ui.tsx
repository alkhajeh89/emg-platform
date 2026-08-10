import Link from "next/link";

export function StatusMark({ tone = "online" }: Readonly<{ tone?: "online" | "planned" }>) {
  return <span className={`status-mark status-mark--${tone}`} aria-hidden="true" />;
}

export function PageHeader({ eyebrow, title, body }: Readonly<{ eyebrow: string; title: string; body: string }>) {
  return <header className="page-header"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{body}</p></header>;
}

export function SectionHeader({ title, label, id }: Readonly<{ title: string; label?: string; id?: string }>) {
  return <header className="section-header"><h2 id={id}>{title}</h2>{label && <span className="data-label">{label}</span>}</header>;
}

export function EmptyState({ title, body }: Readonly<{ title: string; body: string }>) {
  return <div className="empty-state"><span className="empty-state__mark" aria-hidden="true">⌁</span><h3>{title}</h3><p>{body}</p></div>;
}

export function ActionLink({ href, children, secondary = false }: Readonly<{ href: string; children: React.ReactNode; secondary?: boolean }>) {
  return <Link className={secondary ? "button button--secondary" : "button"} href={href}>{children}</Link>;
}
