"""Independent downstream Delegated-Credential validator -- ADR-038 §7.6 /
AC-9 ("downstream Platform Services independently validate Delegated
Credentials before authorization evaluation").

Deliberately mirrors, field-for-field, the validation contract already
implemented in production at
`services/knowledge-graph/src/emg_knowledge_graph_api/authn.py`'s
`TenantServiceTokenValidator.validate()`: RS256 signature verified against
the realm JWKS, issuer checked, audience checked, `exp`/`iat`/`iss`/`aud`
required present. This module does not import that production code (per
this repo's own established "each service validates independently, no
shared broker" convention, restated in that same file's docstring) -- it
reproduces the identical contract so the verification evidence is
comparable to what production already does, not a weaker or different
check invented for this harness.

One instance per downstream audience, constructed with that audience's own
expected `aud` value -- this is what makes "independent" true: Audience A's
validator has no way to accept a token whose `aud` is Audience B, and vice
versa, without needing to know anything about how the other audience is
configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import jwt


class DownstreamValidationError(Exception):
    """Fail-closed: every rejection reason -- bad signature, wrong issuer,
    wrong audience, expired, missing required claim -- raises this single
    type. Callers never see a raw jwt.PyJWTError or other library
    exception, matching production's AuthorizationError pattern."""


@dataclass(frozen=True)
class DownstreamAudienceValidator:
    issuer: str
    audience: str
    jwks_uri: str
    jwks_cache_ttl_seconds: int = 5

    def _jwks_client(self) -> jwt.PyJWKClient:
        return jwt.PyJWKClient(self.jwks_uri, lifespan=self.jwks_cache_ttl_seconds)

    def validate(self, token: str) -> dict[str, Any]:
        try:
            signing_key = self._jwks_client().get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                cast(Any, signing_key),
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise DownstreamValidationError(f"Invalid delegated credential: {exc}") from exc
        return payload
