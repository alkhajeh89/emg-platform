import pytest
from emg_errors import EMGError, ValidationError


def test_base_error_message_and_code():
    err = EMGError("something failed")
    assert err.message == "something failed"
    assert err.error_code == "EMG_ERROR"


def test_subclass_default_error_code():
    err = ValidationError("bad input")
    assert err.error_code == "VALIDATION_ERROR"
    with pytest.raises(ValidationError):
        raise err
