from emg_auth_client import (
    AuthorizationRequest,
    Decision,
    Principal,
    ServicePrincipalLike,
)


def test_principal_defaults():
    p = Principal(subject="user-123")
    assert p.subject == "user-123"
    assert p.roles == ()
    assert p.attributes == {}


# --- Sprint 4: FEAT-03-1 Policy Enforcement Point contract -----------------


def test_decision_allowed_property():
    allow = Decision(outcome="allow", reason="matched policy platform-user-read")
    deny = Decision(outcome="deny", reason="no matching policy rule (default-deny)")
    assert allow.allowed is True
    assert deny.allowed is False


def test_authorization_request_defaults_resource_attributes_to_empty_dict():
    principal = Principal(subject="dev.investigator", roles=("platform-user",))
    request = AuthorizationRequest(
        principal=principal, resource_type="identity.diagnostics", action="read"
    )
    assert request.resource_attributes == {}


def test_service_principal_like_is_structural_not_nominal():
    """A plain object with the right shape satisfies ServicePrincipalLike
    without inheriting from it or importing emg_identity — proves the
    Protocol is genuinely structural (Sprint 4 design decision).

    `attributes` (ADR-026 Revision 2, Amendment 2) is part of that shape now
    — a class missing it no longer structurally satisfies the Protocol."""

    class FakeServicePrincipal:
        client_id = "emg-svc-example"
        service_name = "example"
        roles: tuple[str, ...] = ("service-account",)
        scopes: tuple[str, ...] = ()
        attributes: dict[str, str] = {}

    fake = FakeServicePrincipal()
    assert isinstance(fake, ServicePrincipalLike)


def test_service_principal_like_requires_attributes_since_adr_026_revision_2():
    """A class with the pre-ADR-026 shape (no `attributes`) no longer
    satisfies ServicePrincipalLike — proves the Protocol extension is real,
    not just documentation."""

    class LegacyServicePrincipal:
        client_id = "emg-svc-legacy"
        service_name = "legacy"
        roles: tuple[str, ...] = ("service-account",)
        scopes: tuple[str, ...] = ()

    legacy = LegacyServicePrincipal()
    assert not isinstance(legacy, ServicePrincipalLike)
