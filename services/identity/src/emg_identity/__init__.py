"""emg_identity — EMG Identity Service.

Implements Module 4 (Identity & Authentication), Sprint 2 scope:

- FEAT-02-1 Identity Provider Integration — Keycloak realm/client backed
  authentication (keycloak_client.py).
- FEAT-02-2 Authentication Session Management — EMG session issuance,
  refresh, and expiry (session.py), independent of Keycloak's own token
  lifetimes so downstream services depend on one EMG-governed session
  contract rather than Keycloak's directly.

Out of Sprint 2 scope (see services/identity/README.md): FEAT-02-3 (Service
Identity & M2M Auth) and FEAT-02-4 (Identity Federation Readiness / air-gapped)
land in Sprint 3.
"""

__version__ = "0.2.0"
