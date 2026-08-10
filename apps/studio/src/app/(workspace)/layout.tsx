import { ApplicationShell } from "@/components/application-shell";

export default function WorkspaceLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <ApplicationShell>{children}</ApplicationShell>;
}
