"""emg_auth_client — auth client and Policy Enforcement Point interfaces.

Scaffolded in Sprint 1 (FEAT-01-2 / Engineering Master Plan §2: "auth client
(Module 4/5) ... as empty, versioned packages other services will depend on
from day one"). This package defines the *shape* every service programs
against; it contains NO Module 4 (Identity) or Module 5 (Authorization)
concrete implementation.

- `AuthClient`/`Principal`: Module 4 (Identity) contract, implemented by
  `services/identity` starting EPIC-02 (Sprint 2/3).
- `PolicyEnforcementPoint`/`Decision`/`AuthorizationRequest`/
  `ServicePrincipalLike`: Module 5 (Authorization) contract, added Sprint 4
  (FEAT-03-1). The default concrete implementation is the separate
  `emg-policy-engine` package (FEAT-03-2).

Every Sprint 1–3 export below keeps its exact name and behavior; Sprint 4's
additions are purely additive.
"""

from .decision import Decision, DecisionOutcome
from .pep import AuthorizationRequest, AuthorizedIdentity, PolicyEnforcementPoint
from .principal import Principal
from .protocol import AuthClient
from .service_principal_protocol import ServicePrincipalLike

__version__ = "0.2.0"

__all__ = [
    "Principal",
    "AuthClient",
    "Decision",
    "DecisionOutcome",
    "AuthorizationRequest",
    "AuthorizedIdentity",
    "PolicyEnforcementPoint",
    "ServicePrincipalLike",
    "__version__",
]
