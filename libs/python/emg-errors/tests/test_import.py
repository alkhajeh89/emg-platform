import pytest
from emg_errors import AuthorizationError, EMGError, PermissionDeniedError, ValidationError


def test_base_error_message_and_code():
    err = EMGError("something failed")
    assert err.message == "something failed"
    assert err.error_code == "EMG_ERROR"


def test_subclass_default_error_code():
    err = ValidationError("bad input")
    assert err.error_code == "VALIDATION_ERROR"
    with pytest.raises(ValidationError):
        raise err


def test_permission_denied_error_default_code():
    err = PermissionDeniedError("caller lacks the required role")
    assert err.error_code == "PERMISSION_DENIED"
    with pytest.raises(PermissionDeniedError):
        raise err


def test_permission_denied_is_distinct_from_authorization_error():
    # ADR-025 §8.6: authentication failure (AuthorizationError, 401) and
    # authorization/policy denial (PermissionDeniedError, 403) are
    # deliberately different types, not the same error reused for two
    # meanings.
    assert not issubclass(PermissionDeniedError, AuthorizationError)
    assert not issubclass(AuthorizationError, PermissionDeniedError)
    assert PermissionDeniedError.error_code != AuthorizationError.error_code
