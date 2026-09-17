# Securpost for Home Assistant (app API)

Fork of [NovleeSAS/securpost-integration-ha](https://github.com/NovleeSAS/securpost-integration-ha)
that signs in with your Securpost account instead of OAuth, so it can also show
the mailbox content photos that Premium subscribers get in the mobile app. See
[upstream issue #2](https://github.com/NovleeSAS/securpost-integration-ha/issues/2).

> Unofficial: this fork is not made, endorsed or supported by Securpost. The
> Securpost name and logo belong to Securpost.

It uses its own `securpost_app` domain, so it installs alongside upstream
rather than replacing it. With both set up you get two devices per mailbox and
Home Assistant suffixes the duplicate entity IDs (`..._2`) — worth renaming the
devices so you can tell them apart.

Connect your Securpost smart mailbox to Home Assistant. You get the current
mailbox contents, the number of deliveries waiting, and an event you can use to
trigger automations when mail arrives.

## Entities

Every mailbox shows up as a Home Assistant device with eleven entities:

- `sensor.<name>_mailbox_content` — what was last detected: Letter, Parcel,
  Empty or Unknown (translated to your HA language). It keeps its value across
  restarts, so you can put it on a dashboard card.
- `sensor.<name>_packages_awaiting` — how many deliveries are waiting to be
  picked up.
- `event.<name>_mailbox_event` — fires on each new mailbox event. Use this in
  automations. The attributes are described [below](#event-attributes).
- `image.<name>_mailbox_content_photo` — the photo taken for the latest event.
  See [Content photos](#content-photos).

Plus seven diagnostic entities, hidden by default under the device page:

- `sensor.<name>_battery` — battery level in percent.
- `binary_sensor.<name>_battery_low` — the mailbox's own low-battery warning,
  which is more trustworthy than a threshold on the percentage.
- `binary_sensor.<name>_connection` — whether the mailbox is still reporting.
- `binary_sensor.<name>_securpost_premium` — whether this mailbox has an active
  subscription, which is what decides if the photo entity ever holds anything.
- `binary_sensor.<name>_email_notifications` and
  `binary_sensor.<name>_push_notifications` — whether Securpost notifies you by
  email and in the app. The email entity carries the configured recipients in a
  `recipients` attribute, so those addresses land in your recorder database.
- `sensor.<name>_reminder_interval` — how many days Securpost waits before
  reminding you that mail is still waiting.

These four mirror what you set in the mobile app and are read-only. Writing
them back means a `PUT` on the whole device object, and getting that body wrong
would silently drop your recipient list, so the integration does not try.

Battery telemetry rides on the events, not on the device, so both battery
entities show the level at the mailbox's last wake-up and stay unknown until it
has sent one event.

You sign in with your Securpost account — the same email and password as the
mobile app — because the photos are only served on the app's own API. The
credentials are stored in the config entry so the session can be renewed
without prompting; like any HA config entry, that means in plain text under
`.storage/core.config_entries`. If the session is ever rejected, HA asks you to
sign in again. One Securpost account per Home Assistant instance, polled once a
minute — and if the API rate-limits the integration, it backs off up to 15
minutes rather than retrying at the same rate.

> This uses the Securpost app API, which is not a published interface and can
> change without notice. The narrower OAuth API the upstream integration uses
> carries no photos.

## Install

You need Home Assistant 2026.5.4 or later and [HACS](https://hacs.xyz).

Fastest way:

1. [![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=carsso&repository=securpost-integration-ha-app-unofficial&category=integration)
   then click **Download**.
2. Restart Home Assistant.
3. [![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=securpost_app),
   or go to **Settings → Devices & Services → Add Integration** and search for
   Securpost (app API).
4. Enter your Securpost email and password, and the verification code if your
   account uses two-factor authentication. Your mailboxes are added on their
   own — you can connect before pairing any mailbox; its entities appear
   automatically once it is paired.

If the badges don't work, add the repo by hand: in HACS open
**Integrations → ⋮ → Custom repositories**, paste
`https://github.com/carsso/securpost-integration-ha-app-unofficial`, pick the
**Integration** category, then download Securpost and restart. Set it up from
**Settings → Devices & Services** as above.

## Event attributes

`event.<name>_mailbox_event` mirrors the API. Its state (`event_type`) is the
mailbox state lowercased, and each event carries these attributes:

- `event_type`: `mailbox_closed`, `mailbox_open` or `unknown`
- `device_state`: `MAILBOX_CLOSED`, `MAILBOX_OPEN` or `UNKNOWN`
- `trigger`: `DETECTION` or `DEVICE_INIT`
- `device_content`: `LETTER`, `PARCEL`, `EMPTY`, `UNKNOWN` or `null`
- `id` and `created_at`: the event's id and timestamp

For dashboards use `sensor.<name>_mailbox_content` instead. The event only
updates when something happens, while the sensor always holds the current value
and persists across restarts.

If several events land between two polls, all of them fire, oldest first — the
devices snapshot only carries the newest one, so the history endpoint fills the
gap. At most ten are replayed per mailbox per cycle. Events from before Home
Assistant started are never replayed: they would arrive with a "now" timestamp
and trigger automations for mail you collected hours ago.

## Content photos

Securpost photographs the mailbox contents on each delivery and serves that
photo to Securpost Premium subscribers. `image.<name>_mailbox_content_photo`
carries the picture for the mailbox's most recent event.

Without a Premium subscription the entity exists but stays empty — the API
returns no photo, which is not treated as an error.

The image is fetched lazily, the first time Home Assistant renders it after a
new event, and then cached until the next event. Putting it on a dashboard you
rarely open costs nothing.

## Example automation

```yaml
trigger:
  - platform: state
    entity_id: event.front_door_mailbox_event
condition:
  - "{{ trigger.to_state.attributes.event_type == 'mailbox_closed' }}"
  - "{{ trigger.to_state.attributes.device_content == 'LETTER' }}"
action:
  - service: notify.mobile_app
    data:
      title: "Mail arrived"
      message: "A letter was just dropped in your mailbox"
      data:
        image: /api/image_proxy/image.front_door_mailbox_content_photo
```

## Support

Open an issue at
<https://github.com/carsso/securpost-integration-ha-app-unofficial/issues>.

Anything that is not about the account sign-in or the photos probably belongs
upstream instead.

## Development

With Home Assistant installed in your environment:

```console
python3 tests/test_app_api.py
```

The tests run against a mock that mirrors the live API, including its rule that
a POST carrying a session cookie must present a trusted `Origin` header.

## License

MIT, see [LICENSE](./LICENSE).
