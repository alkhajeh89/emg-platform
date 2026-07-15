"""emg_auth_client — auth client interface/conventions.

Scaffolded in Sprint 1 (FEAT-01-2 / Engineering Master Plan §2: "auth client
(Module 4/5) ... as empty, versioned packages other services will depend on
from day one"). This package defines the *shape* every service programs
against; it contains NO Module 4 (Identity) or Module 5 (Authorization)
implementation, which is explicitly out of Sprint 1 scope and lands in
EPIC-02/EPIC-03.
"""

from .principal import Principal
from .protocol import AuthClient

__version__ = "0.1.0"

__all__ = ["Principal", "AuthClient", "__version__"]
