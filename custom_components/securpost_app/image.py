"""Image entity: the photo of the mailbox content for the latest event."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, final, override

from homeassistant.components.image import ImageEntity

from .api.errors import SecurpostApiError
from .entity import SecurpostDeviceEntity, async_add_entities_for_new_devices

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SecurpostConfigEntry
    from .api.models import MailboxEvent
    from .coordinator import SecurpostDataCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: SecurpostConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the content photo entities, adding them as devices appear."""
    coordinator = entry.runtime_data
    async_add_entities_for_new_devices(
        entry,
        async_add_entities,
        lambda device_id: (MailboxContentImage(coordinator, device_id),),
    )


@final
class MailboxContentImage(  # pyright: ignore[reportIncompatibleVariableOverride]
    SecurpostDeviceEntity, ImageEntity
):
    """Photo taken for the mailbox's most recent event.

    Premium-only: without a subscription the API returns no photo, and the
    entity simply stays empty rather than erroring on every poll.
    """

    _attr_translation_key = "mailbox_photo"

    def __init__(self, coordinator: SecurpostDataCoordinator, device_id: str) -> None:
        """Initialize the photo entity for a single device."""
        super().__init__(coordinator, device_id)
        ImageEntity.__init__(self, coordinator.hass)
        self._attr_unique_id = f"{device_id}_mailbox_photo"
        # Photos are fetched lazily, on the first HA request per event, and held
        # until a newer event arrives — polling every mailbox for a picture
        # nobody is looking at would be a lot of traffic for nothing.
        self._cached_event_id: str | None = None
        self._cached_image: bytes | None = None

    @property
    @override
    def image_last_updated(self) -> datetime | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Timestamp of the event the current photo belongs to."""
        event = self._last_event()
        return event.created_at if event is not None else None

    @override
    async def async_image(self) -> bytes | None:
        """Return the photo bytes for the latest event, or None when there is none."""
        event = self._last_event()
        if event is None or event.photo_url is None:
            return None
        if event.id == self._cached_event_id:
            return self._cached_image
        try:
            image = await self.coordinator.client.fetch_photo(event.photo_url)
        except SecurpostApiError as err:
            _LOGGER.debug(
                "No photo for event %s on device %s: %s", event.id, self._device_id, err
            )
            return None
        self._cached_event_id = event.id
        self._cached_image = image
        return image

    def _last_event(self) -> MailboxEvent | None:
        device = self.coordinator.data.devices.get(self._device_id)
        return device.last_event if device else None
