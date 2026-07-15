"""emg_policy_engine — local ABAC policy evaluation (Module 5 Authorization
& Policy Platform, FEAT-03-2), and the default `PolicyEnforcementPoint`
implementation (FEAT-03-1) built on top of it.

Added Sprint 4. Depends on `emg_auth_client` for the shared
`PolicyEnforcementPoint`/`Decision`/`AuthorizationRequest` contract this
package implements — see `docs/engineering/sprint-4-design.md`.
"""

from .engine import PolicyEngine
from .loader import default_policy_config, load_policy_config, validate_policy_config
from .pep import LocalPolicyEnforcementPoint
from .rules import PolicyConfig, PolicyRule

__version__ = "0.1.0"

__all__ = [
    "PolicyEngine",
    "PolicyConfig",
    "PolicyRule",
    "default_policy_config",
    "load_policy_config",
    "validate_policy_config",
    "LocalPolicyEnforcementPoint",
    "__version__",
]
