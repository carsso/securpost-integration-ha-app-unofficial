#!/usr/bin/env python3
"""Checks against a mock that mirrors how the real API behaves.

Run with `python3 tests/test_app_api.py` from the repo root, in an environment
that has Home Assistant installed. No pytest, no HA test harness.

The mock enforces the rules the live API was observed to enforce — notably that
any POST carrying a session cookie must present a trusted Origin.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.securpost_app.api.auth import (  # noqa: E402
    SecurpostAuth,
    TwoFactorMode,
    TwoFactorRequired,
)
from custom_components.securpost_app.api.client import (  # noqa: E402
    SecurpostAppClient,
    _parse_device,
)
from custom_components.securpost_app.api.errors import (  # noqa: E402
    SecurpostApiError,
    SecurpostAuthError,
)
from custom_components.securpost_app.api.models import (  # noqa: E402
    Battery,
    Device,
    DeviceContent,
    DeviceState,
    MailboxEvent,
    Trigger,
)
from custom_components.securpost_app.const import (  # noqa: E402
    APP_ORIGIN,
    SESSION_COOKIE_NAME,
)
from custom_components.securpost_app.coordinator import (  # noqa: E402
    SecurpostCoordinatorData,
)
from custom_components.securpost_app.image import MailboxContentImage  # noqa: E402

COOKIE = f"__Secure-{SESSION_COOKIE_NAME}"
TRUSTED = {"securpost://", "https://user.securpost.com", "https://api.securpost.app"}

DEVICES = {
    "total": 1, "hasNextPage": False, "pages": 1, "totalAvailableBatchCount": 2,
    "userDevices": [{
        "id": "dev-1", "name": "Front door", "icon": "mailbox", "active": True,
        "disconnected": False, "status": "OK", "shareCode": "ABC123",
        "availableBatchCount": 2, "subscription": {"isActive": True},
        "notificationPushEnabled": True, "notificationMailEnabled": True,
        "notificationMails": ["me@example.com", "flat@example.com"],
        "remindNotificationEvery": 3,
        "lastHistory": {
            "id": "ev-9", "trigger": "DETECTION", "deviceState": "MAILBOX_CLOSED",
            "deviceContent": "LETTER",
            "image": {"state": "AVAILABLE", "resolution": "HIGH",
                      "url": "/media/photos/ev-9.jpg"},
            "battery": {"level": 87, "low": False},
            "createdAt": "2026-09-08T10:11:12+00:00",
            "updatedAt": "2026-09-08T10:11:12+00:00"},
    }],
}
FREE_DEVICE = {
    "id": "dev-2", "name": "Free plan", "disconnected": False,
    "availableBatchCount": 0, "subscription": {"isActive": False},
    "lastHistory": {
        "id": "ev-1", "trigger": "DEVICE_INIT", "deviceState": "UNKNOWN",
        "deviceContent": None, "image": {"state": "UNAVAILABLE", "url": None},
        "battery": {"level": 55, "low": False},
        "createdAt": "2026-09-07T10:11:12+00:00"},
}

def _event(event_id: str, when: str) -> dict:
    return {"id": event_id, "trigger": "DETECTION", "deviceState": "MAILBOX_CLOSED",
            "deviceContent": "LETTER", "image": {"state": "AVAILABLE", "url": None},
            "battery": {"level": 80, "low": False},
            "createdAt": when, "updatedAt": when}


# Deliberately out of order: the client must sort, not trust the server.
HISTORY = {"total": 3, "hasNextPage": False, "pages": 1, "deviceHistories": [
    _event("ev-8", "2026-09-08T09:00:00+00:00"),
    _event("ev-9", "2026-09-08T10:11:12+00:00"),
    _event("ev-7", "2026-09-08T08:00:00+00:00"),
]}

state = {"two_factor": False}
passed = failed = 0


def check(label: str, condition: bool) -> None:
    global passed, failed  # noqa: PLW0603
    if condition:
        passed += 1
        print("ok  ", label)
    else:
        failed += 1
        print("FAIL", label)


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if (
        request.method == "POST"
        and request.headers.get("cookie")
        and request.headers.get("origin") not in TRUSTED
    ):
        return httpx.Response(403, json={"message": "Missing or null Origin",
                                         "code": "MISSING_OR_NULL_ORIGIN"})
    if path.endswith("/sign-in/email"):
        if json.loads(request.content)["password"] != "good":
            return httpx.Response(401, json={"message": "Invalid email or password"})
        if state["two_factor"]:
            return httpx.Response(200, json={"twoFactorRedirect": True})
        return httpx.Response(200, json={"redirect": False},
                              headers={"set-cookie": f"{COOKIE}=tok-abc; Path=/"})
    if path.endswith("/two-factor/send-otp"):
        return httpx.Response(400, json={})
    if path.endswith("/two-factor/verify-totp"):
        if json.loads(request.content)["code"] != "123456":
            return httpx.Response(401, json={"message": "Invalid code"})
        return httpx.Response(200, json={"status": True},
                              headers={"set-cookie": f"{COOKIE}=tok-2fa; Path=/"})
    if path.endswith("/get-session"):
        return httpx.Response(200, json={"user": {"id": "u1"}}
                              if request.headers.get("cookie") else None)
    if path == "/customer/user-devices":
        return httpx.Response(200, json=DEVICES)
    if path == "/customer/user-devices/dev-1/history":
        if state.get("history_broken"):
            return httpx.Response(500, json={})
        return httpx.Response(200, json=HISTORY)
    if path == "/customer/user-devices/limited/history":
        return httpx.Response(429, json={"message": "Too many requests"})
    if path == "/media/photos/ev-9.jpg":
        return httpx.Response(200, content=b"\xff\xd8JPEG")
    return httpx.Response(404, json={})


def client(origin: str | None = APP_ORIGIN) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.securpost.app",
        headers={"Origin": origin} if origin else {},
        transport=httpx.MockTransport(handler),
    )


async def test_auth() -> None:
    async with client() as http:
        try:
            await SecurpostAuth(http).sign_in("a@b.c", "bad")
            check("wrong password is rejected", False)
        except SecurpostAuthError:
            check("wrong password is rejected", True)

    async with client() as http:
        auth = SecurpostAuth(http)
        check("sign-in returns no second factor", await auth.sign_in("a@b.c", "good") is None)
        check("session cookie keeps its __Secure- name", auth.session_cookie == (COOKIE, "tok-abc"))

    async with client() as http:
        auth = SecurpostAuth(http)
        auth.restore(COOKIE, "tok-restored")
        await auth.get_session()
        check("restored cookie is accepted", auth.session_cookie == (COOKIE, "tok-restored"))

    # Regression: a stale cookie plus no Origin is what broke setup in HA.
    async with client(origin=None) as http:
        auth = SecurpostAuth(http)
        auth.restore(COOKIE, "stale")
        try:
            await auth.sign_in("a@b.c", "good")
            check("cookie-bearing POST without Origin is refused", False)
        except SecurpostAuthError as err:
            check("cookie-bearing POST without Origin is refused", "Origin" in str(err))

    async with client() as http:
        auth = SecurpostAuth(http)
        auth.restore(COOKIE, "stale")
        check("re-signin over a stale cookie works with Origin",
              await auth.sign_in("a@b.c", "good") is None)


async def test_two_factor() -> None:
    state["two_factor"] = True
    async with client() as http:
        auth = SecurpostAuth(http)
        outcome = await auth.sign_in("a@b.c", "good")
        check("2FA account stops at the second factor",
              isinstance(outcome, TwoFactorRequired) and outcome.mode is TwoFactorMode.TOTP)
        try:
            await auth.verify_two_factor("000000", TwoFactorMode.TOTP)
            check("wrong 2FA code is rejected", False)
        except SecurpostAuthError:
            check("wrong 2FA code is rejected", True)
        await auth.verify_two_factor("123456", TwoFactorMode.TOTP)
        check("2FA sets a fresh session cookie", auth.session_cookie == (COOKIE, "tok-2fa"))
    state["two_factor"] = False


async def test_devices() -> None:
    async with client() as http:
        auth = SecurpostAuth(http)
        await auth.sign_in("a@b.c", "good")
        rotated: list[tuple[str, str]] = []
        api = SecurpostAppClient(http, auth, cookie_updated=lambda *c: rotated.append(c))
        device = (await api.list_devices())[0]
        check("userDevices envelope is unwrapped", device.id == "dev-1")
        check("batch count parsed", device.available_batch_count == 2)
        check("battery read off lastHistory", device.battery.level == 87)
        check("content parsed", device.last_event.device_content is DeviceContent.LETTER)
        check("photo url comes with the snapshot",
              device.last_event.photo_url == "/media/photos/ev-9.jpg")
        check("photo fetched", await api.fetch_photo(device.last_event.photo_url) == b"\xff\xd8JPEG")

    free = _parse_device(FREE_DEVICE)
    check("free account has no photo url", free.last_event.photo_url is None)
    check("free account still reports battery", free.battery.level == 55)


WHEN = datetime.datetime(2026, 9, 8, 10, 11, 12, tzinfo=datetime.UTC)


def _device(event_id: str) -> Device:
    return Device(id="dev-1", name="Front door", available_batch_count=1,
                  disconnected=False, battery=Battery(level=90.0, low=False),
                  last_event=MailboxEvent(id=event_id, trigger=Trigger.DETECTION,
                                          device_state=DeviceState.MAILBOX_CLOSED,
                                          device_content=DeviceContent.LETTER,
                                          created_at=WHEN,
                                          photo_url=f"/media/{event_id}.jpg"))


class _Photos:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch_photo(self, url: str) -> bytes:
        self.calls.append(url)
        return b"JPEG"


class _Broken(_Photos):
    async def fetch_photo(self, url: str) -> bytes:
        raise SecurpostApiError("402 payment required")


async def test_image() -> None:
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.data = SecurpostCoordinatorData(devices={"dev-1": _device("ev-9")})
    photos = _Photos()
    coordinator.client = photos
    entity = MailboxContentImage(coordinator, "dev-1")

    check("image entity builds", entity.unique_id == "dev-1_mailbox_photo")
    check("last updated tracks the event", entity.image_last_updated == WHEN)
    await entity.async_image()
    await entity.async_image()
    check("photo fetched once then cached", photos.calls == ["/media/ev-9.jpg"])

    coordinator.data = SecurpostCoordinatorData(devices={"dev-1": _device("ev-10")})
    await entity.async_image()
    check("a new event refetches", photos.calls[-1] == "/media/ev-10.jpg")

    coordinator.client = _Broken()
    coordinator.data = SecurpostCoordinatorData(devices={"dev-1": _device("ev-11")})
    check("a refused photo reads as empty", await entity.async_image() is None)

    coordinator.data = SecurpostCoordinatorData(devices={})
    check("an unpaired mailbox reads as empty", await entity.async_image() is None)


async def test_diagnostics() -> None:
    from custom_components.securpost_app.binary_sensor import (
        BatteryLowBinarySensor,
        ConnectivityBinarySensor,
        PremiumBinarySensor,
    )
    from custom_components.securpost_app.sensor import BatterySensor

    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    device = _device("ev-9")
    coordinator.data = SecurpostCoordinatorData(devices={"dev-1": device})

    battery = BatterySensor(coordinator, "dev-1")
    check("battery level exposed", battery.native_value == 90.0)

    link = ConnectivityBinarySensor(coordinator, "dev-1")
    check("connectivity inverts the API flag", link.is_on is True)

    low = BatteryLowBinarySensor(coordinator, "dev-1")
    check("battery low reads the API warning", low.is_on is False)

    premium = PremiumBinarySensor(coordinator, "dev-1")
    check("premium is off without a subscription", premium.is_on is False)

    from custom_components.securpost_app.binary_sensor import (
        EmailNotificationsBinarySensor,
        PushNotificationsBinarySensor,
    )
    from custom_components.securpost_app.sensor import ReminderIntervalSensor

    configured = _parse_device(DEVICES["userDevices"][0])
    coordinator.data = SecurpostCoordinatorData(devices={"dev-1": configured})
    mail = EmailNotificationsBinarySensor(coordinator, "dev-1")
    check("email notifications reflect the account", mail.is_on is True)
    check("recipients ride along as an attribute",
          mail.extra_state_attributes == {
              "recipients": ["me@example.com", "flat@example.com"]})
    check("push notifications reflect the account",
          PushNotificationsBinarySensor(coordinator, "dev-1").is_on is True)
    check("reminder interval is in days",
          ReminderIntervalSensor(coordinator, "dev-1").native_value == 3)

    bare = _parse_device(FREE_DEVICE)
    check("a device without notification fields falls back to defaults",
          (bare.notifications.email, bare.notifications.email_recipients,
           bare.notifications.remind_after_days) == (False, (), None))

    coordinator.data = SecurpostCoordinatorData(devices={"dev-1": device})
    subscribed = _parse_device(DEVICES["userDevices"][0])
    check("subscription.isActive is parsed", subscribed.subscription_active is True)
    check("free device has no subscription",
          _parse_device(FREE_DEVICE).subscription_active is False)

    offline = Device(id="dev-1", name="Front door", available_batch_count=0,
                     disconnected=True, battery=Battery(level=None, low=True),
                     last_event=None)
    coordinator.data = SecurpostCoordinatorData(devices={"dev-1": offline})
    check("disconnected mailbox reports no connectivity", link.is_on is False)
    check("battery is unknown before any event", battery.native_value is None)
    check("battery low is unknown before any event", low.is_on is None)

    coordinator.data = SecurpostCoordinatorData(devices={})
    check("unpaired mailbox leaves the flags unknown",
          (link.is_on, low.is_on, premium.is_on) == (None, None, None))


async def test_history_replay() -> None:
    from custom_components.securpost_app.coordinator import (
        MAX_BACKOFF_SECONDS,
        SecurpostDataCoordinator,
    )

    async with client() as http:
        auth = SecurpostAuth(http)
        await auth.sign_in("a@b.c", "good")
        api = SecurpostAppClient(http, auth)

        history = await api.list_history("dev-1")
        check("history envelope is deviceHistories",
              [e.id for e in history] == ["ev-9", "ev-8", "ev-7"])

        entry = MagicMock()
        entry.entry_id = "entry"
        coordinator = SecurpostDataCoordinator(MagicMock(), api, entry)
        device = _parse_device(DEVICES["userDevices"][0])

        missed = await coordinator._events_since(device, "ev-7")
        check("missed events replay oldest first",
              [e.id for e in missed] == ["ev-8", "ev-9"])

        missed = await coordinator._events_since(device, "ev-0")
        check("an event off the page falls back to the newest",
              [e.id for e in missed] == ["ev-9"])

        state["history_broken"] = True
        missed = await coordinator._events_since(device, "ev-7")
        check("unreadable history falls back to the newest",
              [e.id for e in missed] == ["ev-9"])
        state.pop("history_broken")

        base = coordinator.update_interval
        coordinator._apply_backoff()
        first = coordinator.update_interval
        check("a 429 slows the poll down", first > base)
        for _ in range(5):
            coordinator._apply_backoff()
        check("backoff is capped",
              coordinator.update_interval.total_seconds() == MAX_BACKOFF_SECONDS)
        coordinator._reset_interval()
        check("a good poll restores the cadence", coordinator.update_interval == base)


async def test_config_flow() -> None:
    from custom_components.securpost_app import config_flow

    config_flow.create_http_client = client

    def flow(source: str = "user") -> config_flow.SecurpostConfigFlow:
        handler = config_flow.SecurpostConfigFlow()
        handler.context = {"source": source}
        return handler

    step = flow()
    check("the flow opens on a form", (await step.async_step_user())["step_id"] == "user")
    result = await step.async_step_user({"email": "a@b.c", "password": "bad"})
    check("a bad password shows invalid_auth", result.get("errors") == {"base": "invalid_auth"})

    step = flow()
    result = await step.async_step_user({"email": "a@b.c", "password": "good"})
    check("a good password creates the entry", result["type"] == "create_entry")
    check("both cookie name and value are stored",
          (result["data"]["session_cookie_name"], result["data"]["session_token"])
          == (COOKIE, "tok-abc"))

    state["two_factor"] = True
    step = flow()
    result = await step.async_step_user({"email": "a@b.c", "password": "good"})
    check("a 2FA account is sent to the code step", result["step_id"] == "two_factor")
    result = await step.async_step_two_factor({"code": "000000"})
    check("a bad code shows invalid_code", result.get("errors") == {"base": "invalid_code"})
    result = await step.async_step_two_factor({"code": "123456"})
    check("a good code creates the entry", result["type"] == "create_entry")
    state["two_factor"] = False

    step = flow(source="reauth")
    result = await step.async_step_reauth({})
    check("reauth without a stored email asks for one",
          "email" in str(result["data_schema"].schema))


async def main() -> int:
    for suite in (test_auth, test_two_factor, test_devices, test_image,
                  test_diagnostics, test_history_replay, test_config_flow):
        print(f"\n--- {suite.__name__} ---")
        await suite()
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
