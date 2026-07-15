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
    Protocol is genuinely structural (Sprint 4 design decision)."""

    class FakeServicePrincipal:
        client_id = "emg-svc-example"
        service_name = "example"
        roles: tuple[str, ...] = ("service-account",)
        scopes: tuple[str, ...] = ()

    fake = FakeServicePrincipal()
    assert isinstance(fake, ServicePrincipalLike)
