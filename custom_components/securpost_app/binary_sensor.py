"""Binary sensors: link state, battery warning and Premium entitlement."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .entity import SecurpostDeviceEntity, async_add_entities_for_new_devices

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SecurpostConfigEntry
    from .api.models import Device
    from .coordinator import SecurpostDataCoordinator


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: SecurpostConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors, adding entities as devices appear."""
    coordinator = entry.runtime_data
    async_add_entities_for_new_devices(
        entry,
        async_add_entities,
        lambda device_id: (
            ConnectivityBinarySensor(coordinator, device_id),
            BatteryLowBinarySensor(coordinator, device_id),
            PremiumBinarySensor(coordinator, device_id),
            EmailNotificationsBinarySensor(coordinator, device_id),
            PushNotificationsBinarySensor(coordinator, device_id),
        ),
    )


class _SecurpostBinarySensor(  # pyright: ignore[reportIncompatibleVariableOverride]
    SecurpostDeviceEntity, BinarySensorEntity
):
    """Base for the diagnostic flags carried by the devices snapshot."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _key: str

    def __init__(self, coordinator: SecurpostDataCoordinator, device_id: str) -> None:
        """Initialize a diagnostic flag for a single device."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_{self._key}"

    def _device(self) -> Device | None:
        return self.coordinator.data.devices.get(self._device_id)


@final
class ConnectivityBinarySensor(_SecurpostBinarySensor):
    """Whether the mailbox is still reporting to Securpost."""

    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _key = "connectivity"

    @property
    @override
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Connectivity is on when connected, so invert the API's flag."""
        device = self._device()
        return None if device is None else not device.disconnected


@final
class BatteryLowBinarySensor(_SecurpostBinarySensor):
    """The mailbox's own low-battery warning."""

    _attr_translation_key = "battery_low"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _key = "battery_low"

    @property
    @override
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Report the flag only once an event has carried battery telemetry."""
        device = self._device()
        if device is None or device.last_event is None:
            return None
        return device.battery.low


@final
class EmailNotificationsBinarySensor(_SecurpostBinarySensor):
    """Whether Securpost emails this mailbox's deliveries, and to whom.

    Read-only: the setting lives behind a PUT on the device, and the recipient
    list is exposed as an attribute rather than the state, which HA caps at
    255 characters.
    """

    _attr_translation_key = "email_notifications"
    _key = "email_notifications"

    @property
    @override
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return whether email notifications are enabled."""
        device = self._device()
        return None if device is None else device.notifications.email

    @property
    @override
    def extra_state_attributes(self) -> dict[str, list[str]] | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Carry the configured recipients."""
        device = self._device()
        if device is None:
            return None
        return {"recipients": list(device.notifications.email_recipients)}


@final
class PushNotificationsBinarySensor(_SecurpostBinarySensor):
    """Whether Securpost pushes this mailbox's deliveries to the mobile app."""

    _attr_translation_key = "push_notifications"
    _key = "push_notifications"

    @property
    @override
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return whether push notifications are enabled."""
        device = self._device()
        return None if device is None else device.notifications.push


@final
class PremiumBinarySensor(_SecurpostBinarySensor):
    """Whether this mailbox has an active Securpost Premium subscription.

    Worth surfacing because it is what decides whether the content photo
    entity ever holds anything.
    """

    _attr_translation_key = "premium"
    _key = "premium"

    @property
    @override
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return whether the subscription is active."""
        device = self._device()
        return None if device is None else device.subscription_active
