"""DataUpdateCoordinator for Securpost."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, final, override

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.errors import (
    SecurpostApiError,
    SecurpostAuthError,
    SecurpostRateLimitError,
)
from .const import DEFAULT_POLL_INTERVAL_SECONDS, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .api.client import SecurpostApi
    from .api.models import Device, MailboxEvent

_LOGGER = logging.getLogger(__name__)

# Cap on how many missed events one device may replay in a single cycle, so a
# long outage cannot flood automations with a backlog.
MAX_REPLAYED_EVENTS = 10
BACKOFF_FACTOR = 4
MAX_BACKOFF_SECONDS = 900


@dataclass(slots=True)
class SecurpostCoordinatorData:
    """Latest devices snapshot + events newly observed on this poll cycle."""

    devices: dict[str, Device] = field(default_factory=dict)
    new_events: dict[str, list[MailboxEvent]] = field(default_factory=dict)


@final
class SecurpostDataCoordinator(DataUpdateCoordinator[SecurpostCoordinatorData]):
    """Polls the Securpost app API on a fixed cadence.

    `/integrations/v1/config` advertised a poll interval; `/customer/*` has no
    equivalent, so the interval is a local constant.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: SecurpostApi,
        entry: ConfigEntry,
    ) -> None:
        """Wire the coordinator to the API client."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL_SECONDS),
        )
        self.client: SecurpostApi = client
        # Per-device "last seen" event id. On each poll, a device whose `lastEvent.id`
        # differs from what we recorded has produced a new event since the previous cycle.
        # Devices appearing for the first time are recorded silently — HA-restart must
        # not replay stale events with "now" timestamps.
        self._last_event_ids: dict[str, str] = {}

    @override
    async def _async_update_data(self) -> SecurpostCoordinatorData:
        try:
            devices = await self.client.list_devices()
        except SecurpostAuthError as err:
            msg = f"Securpost rejected the session: {err}"
            raise ConfigEntryAuthFailed(msg) from err
        except SecurpostRateLimitError as err:
            self._apply_backoff()
            msg = f"Securpost rate limited the integration: {err}"
            raise UpdateFailed(msg) from err
        except SecurpostApiError as err:
            msg = f"Failed to refresh from Securpost API: {err}"
            raise UpdateFailed(msg) from err

        devices_by_id: dict[str, Device] = {}
        new_events: dict[str, list[MailboxEvent]] = {}
        for device in devices:
            devices_by_id[device.id] = device
            if device.last_event is None:
                continue
            prev_event_id = self._last_event_ids.get(device.id)
            self._last_event_ids[device.id] = device.last_event.id
            if prev_event_id is None or prev_event_id == device.last_event.id:
                continue
            new_events[device.id] = await self._events_since(device, prev_event_id)

        # Drop ids of devices that disappeared from the snapshot. Without this an
        # unpaired-then-repaired mailbox would skip its cold-start replay guard.
        self._last_event_ids = {
            device_id: event_id
            for device_id, event_id in self._last_event_ids.items()
            if device_id in devices_by_id
        }

        self._reset_interval()
        return SecurpostCoordinatorData(devices=devices_by_id, new_events=new_events)

    async def _events_since(
        self, device: Device, prev_event_id: str
    ) -> list[MailboxEvent]:
        """Return the events this device produced since `prev_event_id`.

        The devices snapshot only carries the newest event, so two deliveries
        between two polls would lose one. History fills that gap; if it cannot
        be read, or the previous event has already fallen off the first page,
        fall back to replaying the newest event alone.
        """
        assert device.last_event is not None  # noqa: S101  # caller checked
        try:
            history = await self.client.list_history(device.id)
        except SecurpostApiError as err:
            _LOGGER.debug("History unavailable for %s: %s", device.id, err)
            return [device.last_event]

        missed: list[MailboxEvent] = []
        for event in history:
            if event.id == prev_event_id:
                break
            missed.append(event)
        else:
            _LOGGER.debug(
                "Event %s is no longer in %s's history; replaying only the newest",
                prev_event_id,
                device.id,
            )
            return [device.last_event]

        missed.reverse()
        return missed[-MAX_REPLAYED_EVENTS:]

    def _apply_backoff(self) -> None:
        """Slow the poll down after a 429 rather than retrying at the same rate."""
        current = (self.update_interval or timedelta(0)).total_seconds()
        backed_off = min(
            max(current, DEFAULT_POLL_INTERVAL_SECONDS) * BACKOFF_FACTOR,
            MAX_BACKOFF_SECONDS,
        )
        if backed_off != current:
            _LOGGER.warning("Rate limited by Securpost, polling every %ss", backed_off)
            self.update_interval = timedelta(seconds=backed_off)

    def _reset_interval(self) -> None:
        """Return to the normal cadence once a poll succeeds."""
        normal = timedelta(seconds=DEFAULT_POLL_INTERVAL_SECONDS)
        if self.update_interval != normal:
            self.update_interval = normal
