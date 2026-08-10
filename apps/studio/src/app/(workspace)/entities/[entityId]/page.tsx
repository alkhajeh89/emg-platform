import { EntityWorkspace } from "@/components/entity-workspace";

export default async function EntityDetailPage({ params }: Readonly<{ params: Promise<{ entityId: string }> }>) {
  const { entityId } = await params;
  return <EntityWorkspace initialEntityId={entityId} />;
}
