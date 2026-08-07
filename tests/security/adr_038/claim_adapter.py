"""ADR-038 Phase 3 deliverable: the ONE place in this verification harness
that knows Keycloak 25's raw claim shape for an exchanged (Delegated
Credential) token. Everything downstream of this module -- test assertions,
the capability matrix, a hypothetical production consumer -- sees only the
technology-neutral `DelegatedCredential` shape ADR-038 Chapter V/VII define,
never a raw JWT claim name.

Determined EXPERIMENTALLY against a real Keycloak 25.0 container (see
docs/security/adr-038/02_KEYCLOAK_VERIFICATION_CONFIG.md for the full
trail), not assumed:

- Acting Service identity is carried by `azp` (the authenticated party that
  performed the exchange). Keycloak 25's legacy/preview token-exchange
  implementation never emits an `act` claim in any configuration tried.
- The exchanged token's `sub` -- required for ADR-038 AC-2 Human Subject
  Preservation -- is NOT populated by Keycloak 25's default exchange
  behaviour, even though custom user-attribute mappers correctly resolve
  against the original subject's user model. It required an explicit
  `oidc-usermodel-property-mapper` (user.attribute=id -> claim.name=sub)
  attached to the TARGET AUDIENCE client's default scopes -- claim
  projection during exchange is governed by the audience client's scopes,
  not the requesting (Acting Service) client's. See
  realm/emg-verification-realm.json's `emg-verification-subject-claim`
  scope. This is a required-configuration item, not a workaround: it
  restores standard RFC 8693 behaviour via a standard Keycloak mapper, it
  does not weaken any check.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DelegatedCredential:
    """ADR-038 Chapter VII's technology-neutral Delegated Credential shape."""

    human_subject: str | None
    acting_service: str | None
    audience: tuple[str, ...]
    tenant_id: str | None
    classification_clearance: str | None
    issuer: str
    issued_at: int
    expires_at: int
    jti: str
    scope: str | None


def to_delegated_credential(verified_claims: dict) -> DelegatedCredential:
    """Map an already cryptographically verified claim set (see
    downstream_validator.py -- this function does NOT verify anything
    itself) into ADR-038's Delegated Credential vocabulary.

    `aud` may be a single string or a list per JWT spec; normalized to a
    tuple so callers never branch on either shape.
    """
    raw_aud = verified_claims.get("aud")
    if raw_aud is None:
        audience: tuple[str, ...] = ()
    elif isinstance(raw_aud, str):
        audience = (raw_aud,)
    else:
        audience = tuple(raw_aud)

    return DelegatedCredential(
        human_subject=verified_claims.get("sub"),
        acting_service=verified_claims.get("azp"),
        audience=audience,
        tenant_id=verified_claims.get("tenant_id"),
        classification_clearance=verified_claims.get("classification_clearance"),
        issuer=verified_claims["iss"],
        issued_at=verified_claims["iat"],
        expires_at=verified_claims["exp"],
        jti=verified_claims["jti"],
        scope=verified_claims.get("scope"),
    )
