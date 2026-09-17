"""Shared base entity binding a Securpost device to the HA device registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from homeassistant.helpers.entity import Entity
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SecurpostConfigEntry
    from .coordinator import SecurpostDataCoordinator


class SecurpostDeviceEntity(CoordinatorEntity["SecurpostDataCoordinator"]):
    """Base for entities backed by a single Securpost mailbox device."""

    _attr_has_entity_name: bool = True

    @property
    @override
    def available(self) -> bool:
        """The mailbox must still be present in the latest API snapshot."""
        return super().available and self._device_id in self.coordinator.data.devices

    def __init__(self, coordinator: SecurpostDataCoordinator, device_id: str) -> None:
        """Bind to one device and register it in the device registry.

        Entities are only created for ids present in ``coordinator.data.devices``
        (see ``async_add_entities_for_new_devices``), so the lookup never misses.
        """
        super().__init__(coordinator)
        self._device_id: str = device_id
        device = coordinator.data.devices[device_id]
        self._attr_device_info: DeviceInfo | None = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device.name,
            manufacturer="Securpost",
            model="Mailbox",
        )


@callback
def async_add_entities_for_new_devices(
    entry: SecurpostConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    entity_factory: Callable[[str], Iterable[Entity]],
) -> None:
    """Create entities for current devices and for any appearing on later polls.

    A user can link their account before pairing a mailbox; without the listener,
    entities would only exist for devices present in the first snapshot.
    """
    coordinator = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def _add_new_devices() -> None:
        new_ids = coordinator.data.devices.keys() - known_ids
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            entity for device_id in new_ids for entity in entity_factory(device_id)
        )

    _add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))
