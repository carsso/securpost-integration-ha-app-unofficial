"""better-auth sign-in, the same flow the Securpost mobile and web apps use.

`/integrations/v1` is reachable with an OAuth token but exposes neither the
history nor the content photos. Those live under `/customer/*`, which only
accepts a better-auth session cookie — so the integration signs in as the app
does and keeps that cookie.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, final

import httpx

from custom_components.securpost_app.const import (
    GET_SESSION_PATH,
    SEND_OTP_PATH,
    SESSION_COOKIE_NAME,
    SIGN_IN_PATH,
    SIGN_OUT_PATH,
    VERIFY_OTP_PATH,
    VERIFY_TOTP_PATH,
)

from .errors import SecurpostApiError, SecurpostAuthError, SecurpostTwoFactorError

if TYPE_CHECKING:
    from collections.abc import Mapping

HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403


class TwoFactorMode(StrEnum):
    """Which second factor the account is enrolled in."""

    EMAIL_OTP = "email_otp"
    TOTP = "totp"


@dataclass(frozen=True, slots=True)
class TwoFactorRequired:
    """Sign-in stopped at the second factor; `mode` says how to finish it."""

    mode: TwoFactorMode


def session_cookie_of(cookies: httpx.Cookies) -> tuple[str, str] | None:
    """Pull the better-auth session cookie out of a jar, name included.

    The name is `__Secure-`-prefixed when the server sets secure cookies, so
    match on the suffix — and keep the name, since restoring it under the wrong
    one leaves the server seeing no session at all.
    """
    for name, value in cookies.items():
        if name.endswith(SESSION_COOKIE_NAME):
            return name, value
    return None


@final
class SecurpostAuth:
    """Drives better-auth on a shared httpx client, leaving the cookie in its jar."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        """Bind to the httpx client whose cookie jar carries the session."""
        self._http = http

    def restore(self, name: str, token: str) -> None:
        """Seed the cookie jar from a previously stored session cookie."""
        self._http.cookies.set(name, token, domain=self._http.base_url.host)

    @property
    def session_cookie(self) -> tuple[str, str] | None:
        """Return the current session cookie as (name, value), if signed in."""
        return session_cookie_of(self._http.cookies)

    async def sign_in(
        self, email: str, password: str, probe_two_factor: bool = True
    ) -> TwoFactorRequired | None:
        """Sign in with email + password.

        Returns `None` once the session cookie is set, or a `TwoFactorRequired`
        when the account needs a second factor. `probe_two_factor` is disabled
        when replaying the password step before submitting a code the user
        already holds: probing mails a fresh OTP, which invalidates that code.
        """
        payload = await self._post(
            SIGN_IN_PATH,
            {"email": email, "password": password, "rememberMe": True},
        )
        if payload.get("twoFactorRedirect"):
            mode = (
                await self._detect_two_factor_mode()
                if probe_two_factor
                else TwoFactorMode.TOTP
            )
            return TwoFactorRequired(mode=mode)
        if self.session_cookie is None:
            msg = "Sign-in succeeded but no session cookie was returned"
            raise SecurpostAuthError(msg)
        return None

    async def verify_two_factor(self, code: str, mode: TwoFactorMode) -> None:
        """Submit the second factor and complete the session."""
        path = (
            VERIFY_OTP_PATH if mode is TwoFactorMode.EMAIL_OTP else VERIFY_TOTP_PATH
        )
        try:
            await self._post(path, {"code": code, "trustDevice": True})
        except SecurpostAuthError as err:
            raise SecurpostTwoFactorError(str(err)) from err
        if self.session_cookie is None:
            msg = "Two-factor verification returned no session cookie"
            raise SecurpostAuthError(msg)

    async def get_session(self) -> Mapping[str, Any]:
        """Return the current session payload, raising if it is no longer valid."""
        payload = await self._request("GET", GET_SESSION_PATH, None)
        if not payload:
            msg = "Session is no longer valid"
            raise SecurpostAuthError(msg)
        return payload

    async def sign_out(self) -> None:
        """Best-effort revocation of the session server-side."""
        with suppress(SecurpostApiError):
            await self._post(SIGN_OUT_PATH, {})

    async def _detect_two_factor_mode(self) -> TwoFactorMode:
        """Ask the server to mail an OTP; success means the account uses email OTP.

        Doing this before prompting keeps us to a single verification attempt,
        rather than trying one endpoint and falling back to the other on failure.
        """
        try:
            await self._post(SEND_OTP_PATH, {})
        except SecurpostApiError:
            return TwoFactorMode.TOTP
        return TwoFactorMode.EMAIL_OTP

    async def _post(
        self, path: str, body: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return await self._request("POST", path, body)

    async def _request(
        self, method: str, path: str, body: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        try:
            response = await self._http.request(method, path, json=body)
        except httpx.HTTPError as err:
            msg = f"HTTP error on {path}: {err}"
            raise SecurpostApiError(msg) from err
        if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            raise SecurpostAuthError(_error_message(response))
        if response.is_error:
            msg = f"HTTP error on {path}: {response.status_code}"
            raise SecurpostApiError(msg)
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as err:
            msg = f"Malformed response from {path}: {err}"
            raise SecurpostApiError(msg) from err
        return payload if isinstance(payload, dict) else {}


def _error_message(response: httpx.Response) -> str:
    """Prefer better-auth's own error code/message over a bare status line."""
    try:
        payload = response.json()
    except ValueError:
        return f"Rejected with HTTP {response.status_code}"
    if isinstance(payload, dict):
        return str(
            payload.get("message") or payload.get("code") or response.status_code
        )
    return f"Rejected with HTTP {response.status_code}"
