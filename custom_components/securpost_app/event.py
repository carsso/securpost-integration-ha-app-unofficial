"""Event entity: re-fires each new mailbox event from the API for automations."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from homeassistant.components.event import EventEntity
from homeassistant.core import callback

from .api.models import DeviceState
from .entity import SecurpostDeviceEntity, async_add_entities_for_new_devices

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SecurpostConfigEntry
    from .api.models import MailboxEvent
    from .coordinator import SecurpostDataCoordinator

EVENT_TYPES = [state.value.lower() for state in DeviceState]


def _attributes(event: MailboxEvent) -> dict[str, str | None]:
    """Mirror the API's own values onto the HA event."""
    content = event.device_content
    return {
        "id": event.id,
        "created_at": event.created_at.isoformat(),
        "device_state": event.device_state.value,
        "trigger": event.trigger.value,
        "device_content": content.value if content is not None else None,
    }


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: SecurpostConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Securpost event entities, adding entities as devices appear."""
    coordinator = entry.runtime_data
    async_add_entities_for_new_devices(
        entry,
        async_add_entities,
        lambda device_id: (MailboxEventEntity(coordinator, device_id),),
    )


@final
class MailboxEventEntity(  # pyright: ignore[reportIncompatibleVariableOverride]
    SecurpostDeviceEntity, EventEntity
):
    """Re-fires the device's latest API event, one HA event per new mailbox event."""

    _attr_translation_key = "mailbox_event"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: SecurpostDataCoordinator, device_id: str) -> None:
        """Initialize the event entity for a single device."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_mailbox_event"

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        for event in self.coordinator.data.new_events.get(self._device_id, ()):
            self._trigger_event(event.device_state.value.lower(), _attributes(event))
            # Each event needs its own state write, otherwise a burst collapses
            # into one and automations only ever see the last one.
            self.async_write_ha_state()
        super()._handle_coordinator_update()
