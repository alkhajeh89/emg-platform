from emg_auth_client import Principal


def test_principal_defaults():
    p = Principal(subject="user-123")
    assert p.subject == "user-123"
    assert p.roles == ()
    assert p.attributes == {}
