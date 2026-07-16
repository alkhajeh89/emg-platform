"""emg_policy_engine — local ABAC policy evaluation (Module 5 Authorization
& Policy Platform, FEAT-03-2), and the default `PolicyEnforcementPoint`
implementation (FEAT-03-1) built on top of it.

Added Sprint 4. Depends on `emg_auth_client` for the shared
`PolicyEnforcementPoint`/`Decision`/`AuthorizationRequest` contract this
package implements — see `docs/engineering/sprint-4-design.md`.

Sprint 5 (FEAT-03-3, FEAT-03-4) adds, additively: the RBAC baseline role
catalog (`roles`) — a governed role *vocabulary* the ABAC engine's
`required_roles` conditions draw from, not a second enforcement mechanism —
and the authorization testing harness (`testing`). See
`docs/engineering/sprint-5-design.md`.
"""

from .engine import PolicyEngine
from .loader import default_policy_config, load_policy_config, validate_policy_config
from .pep import LocalPolicyEnforcementPoint
from .roles import ROLE_CATALOG, RoleCategory, RoleDefinition, is_known_role, role_ids
from .rules import PolicyConfig, PolicyRule
from .testing import AuthorizationScenario, assert_scenario, run_scenarios

__version__ = "0.2.0"

__all__ = [
    "PolicyEngine",
    "PolicyConfig",
    "PolicyRule",
    "default_policy_config",
    "load_policy_config",
    "validate_policy_config",
    "LocalPolicyEnforcementPoint",
    # Sprint 5 — FEAT-03-3 RBAC baseline role catalog
    "ROLE_CATALOG",
    "RoleCategory",
    "RoleDefinition",
    "is_known_role",
    "role_ids",
    # Sprint 5 — FEAT-03-4 authorization testing harness
    "AuthorizationScenario",
    "assert_scenario",
    "run_scenarios",
    "__version__",
]
