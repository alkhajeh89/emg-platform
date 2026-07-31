"""Thin audit-read adapter over the platform Policy Enforcement Point."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from emg_auth_client import AuthorizationRequest, PolicyEnforcementPoint
from emg_common_types import Classification
from emg_errors import PermissionDeniedError
from emg_policy_engine import LocalPolicyEnforcementPoint, load_validated_policy_config
from fastapi import Depends

from .authn import ServicePrincipal, ServicePrincipalDep
from .config import get_settings


@dataclass(frozen=True, slots=True)
class AuditReadScope:
    tenant_id: str
    classifications: tuple[Classification, ...]


class AuditReadAuthorizer:
    """Ask the PEP which classifications this verified principal may read."""

    def __init__(self, pep: PolicyEnforcementPoint) -> None:
        self._pep = pep

    def authorize(self, principal: ServicePrincipal) -> AuditReadScope:
        allowed = tuple(
            classification
            for classification in Classification
            if self._pep.authorize(
                AuthorizationRequest(
                    principal=principal,
                    resource_type="audit.event",
                    action="read",
                    resource_attributes={"classification": classification.value},
                )
            ).allowed
        )
        if not allowed:
            raise PermissionDeniedError("principal is not permitted to read audit events")
        return AuditReadScope(
            tenant_id=principal.tenant_id,
            classifications=allowed,
        )


@lru_cache
def _authorizer_singleton() -> AuditReadAuthorizer:
    settings = get_settings()
    policy = load_validated_policy_config(settings.policy_config_path)
    return AuditReadAuthorizer(LocalPolicyEnforcementPoint(policy))


def validate_audit_policy_configuration() -> None:
    """Load and validate the fail-closed policy before serving traffic."""

    _authorizer_singleton()


def audit_read_scope_dependency(principal: ServicePrincipalDep) -> AuditReadScope:
    return _authorizer_singleton().authorize(principal)


AuditReadScopeDep = Annotated[AuditReadScope, Depends(audit_read_scope_dependency)]
