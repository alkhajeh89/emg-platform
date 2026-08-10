"""Cookie policy coverage for HTTPS production and localhost development."""

from __future__ import annotations

from emg_studio_bff.config import Settings
from emg_studio_bff.dependencies import set_session_cookie
from emg_studio_bff.routers.auth import _clear_session_cookie, _set_csrf_cookie
from starlette.responses import Response


def _headers(response: Response) -> list[str]:
    return response.headers.getlist("set-cookie")


def test_cookie_creation_preserves_security_attributes() -> None:
    for secure in (True, False):
        settings = Settings(secure_cookies=secure)
        response = Response()
        set_session_cookie(response, settings, "opaque-session", 300)
        _set_csrf_cookie(response, settings, "csrf-token", 300)

        session, csrf = _headers(response)
        assert ("Secure" in session) is secure
        assert "HttpOnly" in session
        assert "SameSite=lax" in session
        assert "Path=/" in session
        assert ("Secure" in csrf) is secure
        assert "HttpOnly" not in csrf
        assert "SameSite=lax" in csrf
        assert "Path=/" in csrf


def test_cookie_deletion_matches_creation_policy() -> None:
    for secure in (True, False):
        settings = Settings(secure_cookies=secure)
        response = Response()
        _clear_session_cookie(response, settings)

        session, csrf = _headers(response)
        assert ("Secure" in session) is secure
        assert "HttpOnly" in session
        assert "SameSite=lax" in session
        assert "Path=/" in session
        assert ("Secure" in csrf) is secure
        assert "HttpOnly" not in csrf
        assert "SameSite=lax" in csrf
        assert "Path=/" in csrf


def test_secure_cookie_setting_loads_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("EMG_STUDIO_BFF_SECURE_COOKIES", "false")
    assert Settings(_env_file=None).secure_cookies is False
