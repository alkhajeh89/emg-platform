"""Phase 7 -- Delegated Credential lifetime, as its own dedicated evidence
(distinct from, but consistent with, test_negative_delegation.py::test_7).

This verification environment configures an explicit, concrete lifetime --
**60 seconds** -- on the `emg-verification` realm's `accessTokenLifespan`
(realm/emg-verification-realm.json:10) and on every confidential client's
`access.token.lifespan` attribute (same file). This value applies uniformly
to Human Principal tokens, Acting Service tokens, and exchanged Delegated
Credentials alike, because Keycloak 25's legacy/preview token-exchange
implementation does not accept a separate requested lifetime -- the exchanged
token inherits the realm/client access-token lifespan exactly like any other
issued access token (determined experimentally; there is no
`requested_token_lifetime` behaviour to configure in this Keycloak version).

**Why 60s is sufficient for THIS verification environment, and explicitly
NOT a production recommendation:** it is short enough to prove real,
Keycloak-enforced expiry within a single test run (test_7 in
test_negative_delegation.py waits out a real 60s+ expiry, not a mocked
clock) while remaining long enough that the handful of HTTP round-trips each
test performs never race the clock. ADR-038 §7.5 only requires the lifetime
be "bounded" and "as short as operationally practical" -- it does not name a
number, and this file does not invent a platform-wide one. Production's
actual deployment-specific value is a Security Baseline decision, not a
capability-verification output -- see
docs/security/adr-038/06_FINAL_VERIFICATION_REPORT.md, "Remaining
production-only configuration requirements."

**Expiration enforcement** is proven by
`test_negative_delegation.py::test_7_expired_delegated_credential_is_rejected`
(a real 60s+ wait against a real Keycloak-issued credential, not duplicated
here to avoid an unnecessary second ~80s sleep in this suite -- the evidence
already exists and is cited, not skipped).

**Reuse cannot extend the credential's lifetime** (ADR-038 §7.8: "Credential
reuse SHALL NOT extend the credential lifetime") is proven below by two
independent angles: (1) issuing two credentials from the same human subject
token back-to-back and showing each is independently capped at the realm
ceiling from ITS OWN fresh `iat`, never cumulative; (2) attempting to use an
already-issued Delegated Credential itself as the `subject_token` of a
further exchange, and showing that whatever Keycloak does with it, the
result is never a credential whose lifetime exceeds the same realm ceiling.
"""

from __future__ import annotations

import time

import keycloak_client as kc
from downstream_validator import DownstreamAudienceValidator

CONFIGURED_LIFETIME_SECONDS = 60


def _issuer(env: dict) -> str:
    return f"{env['base_url']}/realms/{env['realm']}"


def _jwks_uri(env: dict) -> str:
    return f"{_issuer(env)}/protocol/openid-connect/certs"


def _validator_for(env: dict, audience: str) -> DownstreamAudienceValidator:
    return DownstreamAudienceValidator(
        issuer=_issuer(env), audience=audience, jwks_uri=_jwks_uri(env)
    )


def _human_a_token(env: dict) -> str:
    resp = kc.ropc_login(
        env["base_url"],
        env["realm"],
        "emg-verification-ropc",
        env["EMG_VERIFICATION_ROPC_SECRET"],
        "human-principal-a",
        env["EMG_VERIFICATION_HUMAN_A_PASSWORD"],
    )
    assert resp.status == 200, resp.body
    return resp.body["access_token"]


def test_configured_lifetime_matches_recorded_value(verification_env):
    """Records and proves the concrete value this environment actually uses
    (not assumed from the realm file alone -- read back from a real issued,
    validated credential)."""
    env = verification_env
    subject = _human_a_token(env)
    resp = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject,
        "emg-verification-audience-a",
    )
    assert resp.status == 200, resp.body
    validated = _validator_for(env, "emg-verification-audience-a").validate(
        resp.body["access_token"]
    )

    lifetime = validated["exp"] - validated["iat"]
    assert lifetime == CONFIGURED_LIFETIME_SECONDS, (
        f"expected the realm's configured {CONFIGURED_LIFETIME_SECONDS}s access-token "
        f"lifespan to apply unchanged to the exchanged Delegated Credential, got {lifetime}s"
    )


def test_repeated_exchange_each_credential_independently_bounded_not_extended(verification_env):
    """ADR-038 §7.8: two credentials issued moments apart from the SAME
    human subject token each get their own fresh, independently-bounded
    lifetime -- issuance is never cumulative, and a second call never
    inherits or extends the first call's expiry window."""
    env = verification_env
    subject = _human_a_token(env)

    first = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject,
        "emg-verification-audience-a",
    )
    assert first.status == 200, first.body
    time.sleep(2)
    second = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject,
        "emg-verification-audience-a",
    )
    assert second.status == 200, second.body

    v = _validator_for(env, "emg-verification-audience-a")
    claims_1 = v.validate(first.body["access_token"])
    claims_2 = v.validate(second.body["access_token"])

    assert (
        claims_2["iat"] > claims_1["iat"]
    ), "expected the second exchange to carry a genuinely fresh iat"
    assert claims_1["exp"] - claims_1["iat"] == CONFIGURED_LIFETIME_SECONDS
    assert claims_2["exp"] - claims_2["iat"] == CONFIGURED_LIFETIME_SECONDS
    assert claims_2["exp"] <= claims_1["exp"] + CONFIGURED_LIFETIME_SECONDS + 2, (
        "second credential's expiry must not reflect any cumulative extension "
        "beyond one fresh lifetime window from its own iat"
    )


def test_reexchanging_a_delegated_credential_does_not_extend_beyond_realm_ceiling(verification_env):
    """Attempts the strongest form of 'reuse' -- presenting an
    already-issued Delegated Credential itself as the subject_token of a
    FURTHER exchange (chaining), rather than the original human token.
    Either Keycloak rejects this outright (a Delegated Credential having no
    further exchange rights is itself a valid, arguably stronger,
    satisfaction of 'reuse SHALL NOT extend lifetime' -- there is nothing to
    extend), or, if it succeeds, the resulting credential's lifetime is
    still capped at the same realm ceiling from its own iat, never larger.
    Both outcomes are asserted for; only a credential whose lifetime
    exceeds the realm ceiling would fail this test."""
    env = verification_env
    subject = _human_a_token(env)
    original = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        subject,
        "emg-verification-audience-a",
    )
    assert original.status == 200, original.body
    delegated_credential_token = original.body["access_token"]

    chained = kc.token_exchange(
        env["base_url"],
        env["realm"],
        "emg-verification-bff",
        env["EMG_VERIFICATION_BFF_SECRET"],
        delegated_credential_token,
        "emg-verification-audience-b",
    )
    if chained.status != 200:
        return  # outright rejection of chained re-exchange also satisfies the invariant

    claims = _validator_for(env, "emg-verification-audience-b").validate(
        chained.body["access_token"]
    )
    lifetime = claims["exp"] - claims["iat"]
    assert lifetime <= CONFIGURED_LIFETIME_SECONDS, (
        f"a re-exchanged credential must never carry a longer lifetime than the "
        f"realm ceiling ({CONFIGURED_LIFETIME_SECONDS}s), got {lifetime}s"
    )
