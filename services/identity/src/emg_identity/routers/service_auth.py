"""Service (M2M) session inspection endpoint — Sprint 3 (FEAT-02-3).

Note there is no `/auth/service-token` issuance endpoint here: the identity
service does not broker Client Credentials tokens on behalf of other
services (see services/identity/README.md, "Why the identity service does
not broker M2M tokens" — brokering would require it to hold every service's
secret, violating least privilege). Each service requests its own token
directly from Keycloak using its own client_id/secret
(`KeycloakClient.client_credentials_token`, demonstrated in
tests/test_keycloak_client.py and the integration-test procedure in
services/identity/README.md).

This endpoint exists so a service's token can be validated end-to-end
against a real HTTP surface (useful for the integration-test procedure and
as a "whoami" check any service can call against the identity service).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..dependencies import get_current_service_principal
from ..schemas import ServiceSessionInfoResponse
from ..service_principal import ServicePrincipal

router = APIRouter(prefix="/auth", tags=["service-auth"])

CurrentServicePrincipalDep = Annotated[ServicePrincipal, Depends(get_current_service_principal)]


@router.get("/service-session", response_model=ServiceSessionInfoResponse)
async def service_session_info(principal: CurrentServicePrincipalDep) -> ServiceSessionInfoResponse:
    return ServiceSessionInfoResponse(
        client_id=principal.client_id,
        service_name=principal.service_name,
        roles=list(principal.roles),
        scopes=list(principal.scopes),
    )
