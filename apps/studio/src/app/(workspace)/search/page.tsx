import { SearchWorkspace } from "@/components/search-workspace";

export default async function SearchPage({ searchParams }: Readonly<{ searchParams: Promise<{ q?: string }> }>) {
  const { q = "" } = await searchParams;
  return <SearchWorkspace initialQuery={q} />;
}
