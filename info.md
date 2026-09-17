# Securpost — your connected mailbox in Home Assistant (app API)

Securpost turns your letterbox into a connected mailbox: real-time alerts
when a letter or parcel is dropped in, no subscription, 4G out of the box.
This integration brings that signal into Home Assistant.

Per mailbox:

- An `event` entity that re-fires each mailbox event; its `event_type` is the
  device state lowercased (`mailbox_closed`, `mailbox_open`, `unknown`). The
  raw API values ride on `device_state`, `trigger`, and `device_content`
- A `sensor` for what was last detected in the mailbox
- A `sensor` for the number of deliveries waiting to be picked up
- An `image` with the photo of the mailbox contents, for Premium accounts

You sign in with your Securpost account, the same one you use in the mobile
app. Its own `securpost_app` domain means it runs alongside the upstream
integration instead of replacing it. No mailbox paired yet? Connect anyway;
entities appear automatically once you pair one.

Unofficial fork of the Securpost integration, not endorsed or supported by
Securpost.
