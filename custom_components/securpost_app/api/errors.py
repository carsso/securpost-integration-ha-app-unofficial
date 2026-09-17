"""Exceptions shared by the auth and data halves of the Securpost client."""

from __future__ import annotations


class SecurpostApiError(Exception):
    """Generic error from the Securpost API."""


class SecurpostAuthError(SecurpostApiError):
    """The session was rejected; re-authentication is required."""


class SecurpostTwoFactorError(SecurpostAuthError):
    """The submitted two-factor code was refused."""


class SecurpostRateLimitError(SecurpostApiError):
    """The API asked us to slow down."""
