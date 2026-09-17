"""The Securpost integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .api import create_http_client
from .api.auth import SecurpostAuth, TwoFactorRequired
from .api.client import SecurpostAppClient
from .api.errors import SecurpostApiError, SecurpostAuthError
from .const import CONF_SESSION_COOKIE_NAME, CONF_SESSION_TOKEN, DOMAIN
from .coordinator import SecurpostDataCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceEntry

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.IMAGE,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SecurpostConfigEntry = ConfigEntry[SecurpostDataCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SecurpostConfigEntry) -> bool:
    """Set up Securpost from a config entry."""
    http = create_http_client()
    auth = SecurpostAuth(http)
    name = entry.data.get(CONF_SESSION_COOKIE_NAME)
    if name and (token := entry.data.get(CONF_SESSION_TOKEN)):
        auth.restore(name, token)

    def store_cookie(new_name: str, new_token: str) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_SESSION_COOKIE_NAME: new_name,
                CONF_SESSION_TOKEN: new_token,
            },
        )

    client = SecurpostAppClient(http, auth, cookie_updated=store_cookie)

    # Inner try translates API failures into HA's flow-control exceptions; the outer
    # one closes the HTTP pool on any failure, so a failed setup never leaks it.
    try:
        try:
            await _ensure_session(entry, auth, store_cookie)
            coordinator = SecurpostDataCoordinator(hass, client, entry)
            await coordinator.async_config_entry_first_refresh()
        except SecurpostAuthError as err:
            msg = f"Securpost rejected the session: {err}"
            raise ConfigEntryAuthFailed(msg) from err
        except SecurpostApiError as err:
            msg = f"Could not reach the Securpost API: {err}"
            raise ConfigEntryNotReady(msg) from err
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await client.aclose()
        raise
    return True


async def _ensure_session(
    entry: SecurpostConfigEntry,
    auth: SecurpostAuth,
    store_cookie: Callable[[str, str], None],
) -> None:
    """Reuse the stored session, signing in again when it has expired.

    better-auth sessions are long-lived but do expire; re-running the password
    step keeps that invisible. An account with two-factor enabled can only be
    replayed silently because sign-in was completed with `trustDevice`, so a
    second-factor prompt here means the user has to finish reauth by hand.
    """
    try:
        await auth.get_session()
    except SecurpostAuthError:
        email = entry.data.get(CONF_EMAIL)
        password = entry.data.get(CONF_PASSWORD)
        if not email or not password:
            msg = "No stored credentials to refresh the session with"
            raise SecurpostAuthError(msg) from None
        outcome = await auth.sign_in(email, password, probe_two_factor=False)
        if isinstance(outcome, TwoFactorRequired):
            msg = "Two-factor confirmation is required to sign in again"
            raise SecurpostAuthError(msg)
        cookie = auth.session_cookie
        if cookie is not None:
            store_cookie(*cookie)


async def async_remove_config_entry_device(
    hass: HomeAssistant,  # noqa: ARG001
    entry: SecurpostConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Let the user delete a HA device once the API no longer reports the mailbox."""
    return not any(
        domain == DOMAIN and device_id in entry.runtime_data.data.devices
        for domain, device_id in device_entry.identifiers
    )


async def async_unload_entry(hass: HomeAssistant, entry: SecurpostConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.aclose()
    return unload_ok
