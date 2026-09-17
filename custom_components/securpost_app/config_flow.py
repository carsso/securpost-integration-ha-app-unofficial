"""Config flow for Securpost, signing in the way the mobile app does."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, final

import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .api import create_http_client
from .api.auth import SecurpostAuth, TwoFactorMode, TwoFactorRequired
from .api.errors import SecurpostApiError, SecurpostAuthError, SecurpostTwoFactorError
from .const import CONF_SESSION_COOKIE_NAME, CONF_SESSION_TOKEN, DOMAIN

if TYPE_CHECKING:
    from collections.abc import Mapping

_LOGGER = logging.getLogger(__name__)

CONF_CODE = "code"

USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})
TWO_FACTOR_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})


@final
class SecurpostConfigFlow(ConfigFlow, domain=DOMAIN):
    """Collect Securpost credentials and exchange them for an app session."""

    VERSION = 2

    def __init__(self) -> None:
        """Start with no half-finished sign-in."""
        self._email: str = ""
        self._password: str = ""
        self._two_factor_mode: TwoFactorMode | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Securpost account and sign in."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=USER_SCHEMA)
        self._email = user_input[CONF_EMAIL]
        self._password = user_input[CONF_PASSWORD]
        return await self._attempt_sign_in(step_id="user", schema=USER_SCHEMA)

    async def async_step_two_factor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish a sign-in that stopped at the second factor."""
        if user_input is None:
            return self.async_show_form(
                step_id="two_factor", data_schema=TWO_FACTOR_SCHEMA
            )
        http = create_http_client()
        auth = SecurpostAuth(http)
        try:
            # A fresh client has no pending-2FA cookie, so replay the password
            # step before verifying — better-auth ties the two together.
            outcome = await auth.sign_in(
                self._email, self._password, probe_two_factor=False
            )
            if not isinstance(outcome, TwoFactorRequired):
                return self._entry_for(auth)
            mode = self._two_factor_mode or outcome.mode
            await auth.verify_two_factor(user_input[CONF_CODE], mode)
            return self._entry_for(auth)
        except SecurpostTwoFactorError:
            return self.async_show_form(
                step_id="two_factor",
                data_schema=TWO_FACTOR_SCHEMA,
                errors={"base": "invalid_code"},
            )
        except SecurpostAuthError:
            return self.async_show_form(
                step_id="user", data_schema=USER_SCHEMA, errors={"base": "invalid_auth"}
            )
        except SecurpostApiError:
            return self.async_show_form(
                step_id="two_factor",
                data_schema=TWO_FACTOR_SCHEMA,
                errors={"base": "cannot_connect"},
            )
        finally:
            await http.aclose()

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Start reauth after the API rejected the stored session."""
        self._email = entry_data.get(CONF_EMAIL, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again and mint a fresh session."""
        schema = REAUTH_SCHEMA if self._email else USER_SCHEMA
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=schema
            )
        self._email = user_input.get(CONF_EMAIL, self._email)
        self._password = user_input[CONF_PASSWORD]
        return await self._attempt_sign_in(step_id="reauth_confirm", schema=schema)

    async def _attempt_sign_in(
        self, step_id: str, schema: vol.Schema
    ) -> ConfigFlowResult:
        """Run the password step, branching to 2FA or finishing the entry."""
        http = create_http_client()
        auth = SecurpostAuth(http)
        try:
            outcome = await auth.sign_in(self._email, self._password)
        except SecurpostAuthError:
            return self.async_show_form(
                step_id=step_id, data_schema=schema, errors={"base": "invalid_auth"}
            )
        except SecurpostApiError:
            return self.async_show_form(
                step_id=step_id, data_schema=schema, errors={"base": "cannot_connect"}
            )
        else:
            if isinstance(outcome, TwoFactorRequired):
                self._two_factor_mode = outcome.mode
                return await self.async_step_two_factor()
            return self._entry_for(auth)
        finally:
            await http.aclose()

    def _entry_for(self, auth: SecurpostAuth) -> ConfigFlowResult:
        """Create or update the entry from a signed-in session."""
        cookie = auth.session_cookie
        if cookie is None:  # pragma: no cover - sign_in guarantees a cookie
            return self.async_abort(reason="no_session")
        name, token = cookie
        data = {
            CONF_EMAIL: self._email,
            CONF_PASSWORD: self._password,
            CONF_SESSION_COOKIE_NAME: name,
            CONF_SESSION_TOKEN: token,
        }
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )
        return self.async_create_entry(title=self._email, data=data)
