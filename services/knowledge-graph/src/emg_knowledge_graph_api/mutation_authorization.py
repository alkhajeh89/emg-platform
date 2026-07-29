"""Thin PEP adapter for ADR-027 mutation authorization preflight."""

from __future__ import annotations

from emg_auth_client import (
    AuthorizationRequest,
    AuthorizedIdentity,
    PolicyEnforcementPoint,
    Principal,
)
from emg_errors import PermissionDeniedError
from emg_knowledge_graph import (
    CloseRelationshipCommand,
    CreateEntityCommand,
    MergeEntitiesCommand,
    MutationAuthorizationContext,
    ReplaceEntityCommand,
    ReplaceRelationshipCommand,
)
from emg_knowledge_graph.commands import MutationCommand


def _operation(command: MutationCommand) -> tuple[str, str]:
    if isinstance(command, CreateEntityCommand):
        return "knowledge-graph.entity", "create"
    if isinstance(command, ReplaceEntityCommand):
        return "knowledge-graph.entity", command.action.value
    if isinstance(command, MergeEntitiesCommand):
        return "knowledge-graph.entity", "merge"
    if isinstance(command, ReplaceRelationshipCommand):
        return "knowledge-graph.relationship", "update"
    if isinstance(command, CloseRelationshipCommand):
        return "knowledge-graph.relationship", "retire"
    raise TypeError(f"unsupported mutation command type: {type(command).__name__}")


def _principal_id(principal: AuthorizedIdentity) -> str:
    if isinstance(principal, Principal):
        return principal.subject
    return principal.client_id


class PepMutationAuthorizationEvaluator:
    """Delegate every operation, ownership, and classification decision to the PEP."""

    def __init__(
        self,
        pep: PolicyEnforcementPoint,
        principal: AuthorizedIdentity,
    ) -> None:
        self._pep = pep
        self._principal = principal

    def authorize(
        self,
        command: MutationCommand,
        context: MutationAuthorizationContext,
    ) -> None:
        resource_type, action = _operation(command)
        resource_attributes: dict[str, str] = {}
        if context.current_resources:
            owner = context.current_resources[0].owner
            resource_attributes["owner_matches_principal"] = str(
                owner is not None and owner == _principal_id(self._principal)
            ).lower()

        classifications = (
            tuple(item.classification for item in context.current_resources)
            + context.proposed_classifications
        )
        checks = classifications or (None,)
        for classification in checks:
            attributes = dict(resource_attributes)
            if classification is not None:
                attributes["classification"] = classification.value
            decision = self._pep.authorize(
                AuthorizationRequest(
                    principal=self._principal,
                    resource_type=resource_type,
                    action=action,
                    resource_attributes=attributes,
                )
            )
            if not decision.allowed:
                raise PermissionDeniedError(
                    f"principal is not permitted to {action!r} {resource_type!r}: "
                    f"{decision.reason}"
                )
