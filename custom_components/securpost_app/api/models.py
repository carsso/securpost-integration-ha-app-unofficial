"""Typed models for the Securpost app API.

Hand-written and independent of any HTTP client or wire format: the rest of the
integration imports these dataclasses, never a generated tree. To swap in a
generated (or alternative) client later, have it map its output onto these shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class Trigger(StrEnum):
    """What caused the device to emit an event."""

    DETECTION = "DETECTION"
    DEVICE_INIT = "DEVICE_INIT"


class DeviceState(StrEnum):
    """Physical state of the mailbox when the event fired."""

    MAILBOX_OPEN = "MAILBOX_OPEN"
    MAILBOX_CLOSED = "MAILBOX_CLOSED"
    UNKNOWN = "UNKNOWN"


class DeviceContent(StrEnum):
    """What the device detected inside the mailbox."""

    LETTER = "LETTER"
    PARCEL = "PARCEL"
    EMPTY = "EMPTY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MailboxEvent:
    """A single event reported by a device."""

    id: str
    trigger: Trigger
    device_state: DeviceState
    device_content: DeviceContent | None
    created_at: datetime
    # Set only for Premium accounts, and only on events the device photographed.
    # The devices snapshot may omit it even when the history entry carries one.
    photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class Battery:
    """Battery telemetry for a device."""

    level: float | None
    low: bool


@dataclass(frozen=True, slots=True)
class Notifications:
    """How the mailbox notifies its owner, as configured in the app.

    Read-only here: changing any of it means a PUT on the device, whose body
    contract is not known well enough to risk overwriting the rest.
    """

    push: bool = False
    email: bool = False
    email_recipients: tuple[str, ...] = ()
    # The app labels this one "remind after days".
    remind_after_days: int | None = None


@dataclass(frozen=True, slots=True)
class Device:
    """A Securpost mailbox device and its latest event."""

    id: str
    name: str | None
    available_batch_count: int
    disconnected: bool
    battery: Battery
    last_event: MailboxEvent | None
    subscription_active: bool = False
    notifications: Notifications = field(default_factory=Notifications)
