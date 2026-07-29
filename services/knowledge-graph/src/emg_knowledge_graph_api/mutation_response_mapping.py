"""Pure application-result to mutation-response projection."""

from __future__ import annotations

from emg_knowledge_graph import MutationExecutionResult

from .mutation_schemas import MutationResponse


def mutation_response(result: MutationExecutionResult) -> MutationResponse:
    """Project only ADR-030 Revision 4's fourteen public fields."""

    return MutationResponse(
        tenant_id=result.tenant.value,
        revision_number=result.revision_number,
        content_hash=result.content_hash,
        node_count=result.node_count,
        edge_count=result.edge_count,
        revision_created=result.revision_created,
        nodes_created=result.nodes_created,
        edges_created=result.edges_created,
        node_inputs_merged=result.node_inputs_merged,
        edge_inputs_merged=result.edge_inputs_merged,
        mutation_id=result.mutation_id,
        audit_reference=result.audit_reference,
        replayed=result.replayed,
        timestamp=result.timestamp,
    )
