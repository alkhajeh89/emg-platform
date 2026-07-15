"""Federation readiness inspection endpoints — Sprint 3 (FEAT-02-4).

Both routes are read-only and side-effect-free: they report on the
currently loaded FederationConfig (see ../federation.py), never modify it
and never contact an external identity provider. Config changes are made by
editing the federation configuration file and restarting/reloading the
service (a deliberately simple, auditable operational procedure for a
"readiness" feature — see docs/engineering/federation-readiness.md).
"""

from __future__ import annotations

from fastapi import APIRouter

from ..dependencies import FederationConfigDep
from ..federation import validate_federation_config
from ..schemas import (
    FederationHealthResponse,
    FederationProvidersResponse,
    FederationProviderSummary,
)

router = APIRouter(prefix="/federation", tags=["federation"])


@router.get("/providers", response_model=FederationProvidersResponse)
async def list_providers(config: FederationConfigDep) -> FederationProvidersResponse:
    return FederationProvidersResponse(
        local_fallback_enabled=config.local_fallback_enabled,
        providers=[
            FederationProviderSummary(
                name=p.name,
                provider_type=p.provider_type.value,
                enabled=p.enabled,
                display_name=p.display_name,
                connection_settings=p.redacted_connection_settings(),
            )
            for p in config.providers
        ],
    )


@router.get("/health", response_model=FederationHealthResponse)
async def federation_health(config: FederationConfigDep) -> FederationHealthResponse:
    problems = validate_federation_config(config)
    return FederationHealthResponse(
        valid=not problems,
        problems=problems,
        provider_count=len(config.providers),
        enabled_provider_count=sum(1 for p in config.providers if p.enabled),
        local_fallback_enabled=config.local_fallback_enabled,
    )
