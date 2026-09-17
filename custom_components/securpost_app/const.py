"""Constants for the Securpost integration."""

from __future__ import annotations

import os
from typing import Final

DOMAIN: Final = "securpost_app"

API_BASE_URL: Final = os.getenv("SECURPOST_API_BASE_URL", "https://api.securpost.app")

# better-auth is mounted under /auth/api, overriding the library's default
# /api/auth basePath. Same base the mobile app and user.securpost.com both use.
AUTH_BASE_PATH: Final = "/auth/api"
SIGN_IN_PATH: Final = f"{AUTH_BASE_PATH}/sign-in/email"
SIGN_OUT_PATH: Final = f"{AUTH_BASE_PATH}/sign-out"
GET_SESSION_PATH: Final = f"{AUTH_BASE_PATH}/get-session"
SEND_OTP_PATH: Final = f"{AUTH_BASE_PATH}/two-factor/send-otp"
VERIFY_OTP_PATH: Final = f"{AUTH_BASE_PATH}/two-factor/verify-otp"
VERIFY_TOTP_PATH: Final = f"{AUTH_BASE_PATH}/two-factor/verify-totp"

# The app's own surface. /integrations/v1 only carries devices and events; the
# content photos live here, behind the same session the mobile app uses.
DEVICES_PATH: Final = "/customer/user-devices"
SUBSCRIPTION_PATH: Final = "/customer/users/subscription"

SESSION_COOKIE_NAME: Final = "better-auth.session_token"

# Any POST carrying a session cookie must present a trusted Origin, or the API
# answers MISSING_OR_NULL_ORIGIN. This is the mobile app's own URL scheme.
APP_ORIGIN: Final = "securpost://"

CONF_SESSION_COOKIE_NAME: Final = "session_cookie_name"
CONF_SESSION_TOKEN: Final = "session_token"

# /customer/* has no capabilities endpoint the way /integrations/v1/config did,
# so the cadence is ours to pick.
DEFAULT_POLL_INTERVAL_SECONDS: Final = 60
