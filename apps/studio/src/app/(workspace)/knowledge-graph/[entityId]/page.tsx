import { KnowledgeGraphExplorer } from "@/components/knowledge-graph-explorer";

export default async function KnowledgeGraphEntityPage({
  params,
}: Readonly<{ params: Promise<{ entityId: string }> }>) {
  const { entityId } = await params;
  return <KnowledgeGraphExplorer initialRootId={entityId} />;
}
