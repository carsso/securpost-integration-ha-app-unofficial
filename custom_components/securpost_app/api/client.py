"""HTTP client for the Securpost app API (`/customer/*`).

The rest of the integration depends on the `SecurpostApi` protocol and the
`models` dataclasses, never on this concrete class. That seam keeps the wire
format in one place: to switch to a generated client, implement `SecurpostApi`
and return the same models.

`/customer/*` is not a published interface — `/docs` is behind auth and no
OpenAPI document is served — so the field names below were read off a live
account.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, final
from urllib.parse import urljoin

import httpx

from custom_components.securpost_app.const import API_BASE_URL, DEVICES_PATH

from .errors import SecurpostApiError, SecurpostAuthError, SecurpostRateLimitError
from .models import (
    Battery,
    Device,
    DeviceContent,
    DeviceState,
    MailboxEvent,
    Notifications,
    Trigger,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from .auth import SecurpostAuth

HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_PAYMENT_REQUIRED = 402
HTTP_TOO_MANY_REQUESTS = 429


class SecurpostApi(Protocol):
    """The API surface the integration depends on."""

    async def list_devices(self) -> list[Device]:
        """Return the current snapshot of every visible device."""
        ...

    async def list_history(self, device_id: str) -> list[MailboxEvent]:
        """Return one device's recent events, newest first."""
        ...

    async def fetch_photo(self, url: str) -> bytes | None:
        """Return the bytes of a content photo, or None when it is unavailable."""
        ...

    async def aclose(self) -> None:
        """Release any held network resources."""
        ...


@final
class SecurpostAppClient:
    """Talks to `/customer/*` with the better-auth session cookie in the jar."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        auth: SecurpostAuth,
        cookie_updated: Callable[[str, str], None] | None = None,
    ) -> None:
        """Bind the shared httpx pool and the session it carries."""
        self._http = http
        self._auth = auth
        self._cookie_updated = cookie_updated
        self._cookie = auth.session_cookie

    async def list_devices(self) -> list[Device]:
        """Return the current snapshot of every visible device."""
        raw = await self._get_json(DEVICES_PATH)
        try:
            return [_parse_device(item) for item in _items(raw, "userDevices")]
        except (KeyError, TypeError, ValueError) as err:
            msg = f"Malformed devices payload: {err}"
            raise SecurpostApiError(msg) from err

    async def list_history(self, device_id: str) -> list[MailboxEvent]:
        """Return one device's recent events, newest first."""
        raw = await self._get_json(f"{DEVICES_PATH}/{device_id}/history")
        try:
            events = [_parse_event(item) for item in _items(raw, "deviceHistories")]
        except (KeyError, TypeError, ValueError) as err:
            msg = f"Malformed history payload: {err}"
            raise SecurpostApiError(msg) from err
        return sorted(events, key=lambda event: event.created_at, reverse=True)

    async def fetch_photo(self, url: str) -> bytes | None:
        """Return the bytes of a content photo, or None when it is unavailable.

        Photos are a Premium feature, and an account without a subscription is
        refused the media itself rather than the URL — so a 402 or 404 is
        reported as "no photo" instead of erroring on every poll.
        """
        return await self._get_bytes(url)

    async def aclose(self) -> None:
        """Close the underlying httpx connection pool."""
        await self._http.aclose()

    async def _get_json(self, path: str) -> Any:  # noqa: ANN401  # decoded JSON is untyped
        response = await self._send(path)
        if response is None:  # pragma: no cover - only _get_bytes allows misses
            msg = f"No response body for {path}"
            raise SecurpostApiError(msg)
        try:
            return response.json()
        except ValueError as err:
            msg = f"Malformed response from {path}: {err}"
            raise SecurpostApiError(msg) from err

    async def _get_bytes(self, url: str) -> bytes | None:
        response = await self._send(urljoin(API_BASE_URL, url), allow_missing=True)
        return None if response is None else response.content

    async def _send(
        self, url: str, allow_missing: bool = False
    ) -> httpx.Response | None:
        try:
            response = await self._http.get(url)
        except httpx.HTTPError as err:
            msg = f"HTTP error on {url}: {err}"
            raise SecurpostApiError(msg) from err
        self._sync_cookie()
        if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            msg = "Session rejected"
            raise SecurpostAuthError(msg)
        if response.status_code == HTTP_TOO_MANY_REQUESTS:
            msg = "Rate limited by the Securpost API"
            raise SecurpostRateLimitError(msg)
        if allow_missing and response.status_code in (
            HTTP_NOT_FOUND,
            HTTP_PAYMENT_REQUIRED,
        ):
            return None
        if response.is_error:
            msg = f"HTTP error on {url}: {response.status_code}"
            raise SecurpostApiError(msg)
        return response

    def _sync_cookie(self) -> None:
        """Persist the session cookie whenever better-auth rotates it."""
        cookie = self._auth.session_cookie
        if cookie is not None and cookie != self._cookie:
            self._cookie = cookie
            if self._cookie_updated is not None:
                self._cookie_updated(*cookie)


def _items(raw: Any, key: str) -> Sequence[Mapping[str, Any]]:  # noqa: ANN401
    """Unwrap one of the paginated envelopes the collection endpoints return."""
    if isinstance(raw, dict) and isinstance(raw.get(key), list):
        return raw[key]
    msg = f"Expected a {key} envelope, got {type(raw).__name__}"
    raise SecurpostApiError(msg)


def _parse_device(raw: Mapping[str, Any]) -> Device:
    # Battery telemetry rides on the event, not the device: it is whatever the
    # mailbox reported the last time it woke up to send one.
    last_event: Mapping[str, Any] | None = raw.get("lastHistory")
    battery: Mapping[str, Any] = (last_event or {}).get("battery") or {}
    subscription: Mapping[str, Any] = raw.get("subscription") or {}
    return Device(
        id=raw["id"],
        name=raw.get("name"),
        available_batch_count=int(raw["availableBatchCount"]),
        disconnected=bool(raw["disconnected"]),
        battery=Battery(level=battery.get("level"), low=bool(battery.get("low"))),
        last_event=_parse_event(last_event) if last_event is not None else None,
        subscription_active=bool(subscription.get("isActive")),
        notifications=_parse_notifications(raw),
    )


def _parse_notifications(raw: Mapping[str, Any]) -> Notifications:
    remind = raw.get("remindNotificationEvery")
    return Notifications(
        push=bool(raw.get("notificationPushEnabled")),
        email=bool(raw.get("notificationMailEnabled")),
        email_recipients=tuple(raw.get("notificationMails") or ()),
        remind_after_days=None if remind is None else int(remind),
    )


def _parse_event(raw: Mapping[str, Any]) -> MailboxEvent:
    content = raw.get("deviceContent")
    image: Mapping[str, Any] = raw.get("image") or {}
    return MailboxEvent(
        id=raw["id"],
        trigger=Trigger(raw["trigger"]),
        device_state=DeviceState(raw["deviceState"]),
        device_content=DeviceContent(content) if content is not None else None,
        created_at=datetime.fromisoformat(raw["createdAt"]),
        photo_url=image.get("url"),
    )
