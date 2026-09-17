"""Sensor: number of deliveries waiting in the mailbox."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime

from .api.models import DeviceContent
from .entity import SecurpostDeviceEntity, async_add_entities_for_new_devices

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SecurpostConfigEntry
    from .api.models import MailboxEvent
    from .coordinator import SecurpostDataCoordinator

CONTENT_OPTIONS = [content.value.lower() for content in DeviceContent]


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: SecurpostConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Securpost sensors, adding entities as devices appear."""
    coordinator = entry.runtime_data
    async_add_entities_for_new_devices(
        entry,
        async_add_entities,
        lambda device_id: (
            PackageCountSensor(coordinator, device_id),
            MailboxContentSensor(coordinator, device_id),
            BatterySensor(coordinator, device_id),
            ReminderIntervalSensor(coordinator, device_id),
        ),
    )


@final
class PackageCountSensor(  # pyright: ignore[reportIncompatibleVariableOverride]
    SecurpostDeviceEntity, SensorEntity
):
    """Number of items awaiting pickup, like the mobile app's badge."""

    _attr_translation_key = "package_count"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:mailbox"

    def __init__(self, coordinator: SecurpostDataCoordinator, device_id: str) -> None:
        """Initialize the package count sensor for a single device."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_package_count"

    @property
    @override
    def native_value(self) -> float | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the current package count for this device."""
        device = self.coordinator.data.devices.get(self._device_id)
        return device.available_batch_count if device else None


@final
class MailboxContentSensor(  # pyright: ignore[reportIncompatibleVariableOverride]
    SecurpostDeviceEntity, SensorEntity
):
    """Latest detected mailbox content, mirroring the API's DeviceContent."""

    _attr_translation_key = "mailbox_content"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CONTENT_OPTIONS
    _attr_icon = "mdi:package-variant"

    def __init__(self, coordinator: SecurpostDataCoordinator, device_id: str) -> None:
        """Initialize the mailbox content sensor for a single device."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_mailbox_content"

    @property
    @override
    def native_value(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the current mailbox content, lowercased, or None if unknown."""
        event = self._last_event()
        content = event.device_content if event else None
        return content.value.lower() if content is not None else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, str] | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Carry the raw API enum values for the latest event."""
        event = self._last_event()
        if event is None:
            return None
        return {
            "trigger": event.trigger.value,
            "device_state": event.device_state.value,
        }

    def _last_event(self) -> MailboxEvent | None:
        device = self.coordinator.data.devices.get(self._device_id)
        return device.last_event if device else None


@final
class BatterySensor(  # pyright: ignore[reportIncompatibleVariableOverride]
    SecurpostDeviceEntity, SensorEntity
):
    """Battery level as of the mailbox's last event.

    The API carries battery telemetry on the event, not on the device, so this
    is the level at the last wake-up rather than a live reading.
    """

    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SecurpostDataCoordinator, device_id: str) -> None:
        """Initialize the battery sensor for a single device."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_battery"

    @property
    @override
    def native_value(self) -> float | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the last reported battery level, or None before any event."""
        device = self.coordinator.data.devices.get(self._device_id)
        if device is None or device.last_event is None:
            return None
        return device.battery.level


@final
class ReminderIntervalSensor(  # pyright: ignore[reportIncompatibleVariableOverride]
    SecurpostDeviceEntity, SensorEntity
):
    """How long Securpost waits before reminding you that mail is waiting.

    The app calls this "remind after days", hence the unit.
    """

    _attr_translation_key = "reminder_interval"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SecurpostDataCoordinator, device_id: str) -> None:
        """Initialize the reminder interval sensor for a single device."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_reminder_interval"

    @property
    @override
    def native_value(self) -> float | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the configured reminder interval in days."""
        device = self.coordinator.data.devices.get(self._device_id)
        return None if device is None else device.notifications.remind_after_days
