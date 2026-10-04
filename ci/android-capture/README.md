# Cooperative screenshot events on Android

An account-local setting, off by default, uses Android 14's activity callback
while an ordinary human-to-human cloud chat is active. The native menu and
dialog explain that enabling it reports **the owner's own screenshots** to the
other person. It is not a detector for uncooperative clients.

The callback is registered only for an enabled, owned, foreground chat. Pause,
fragment destruction, logout, owner changes and passcode locking revoke it.
Window focus, modal dialogs and existing photo/secret-media viewers are checked
before reporting. API-34 types stay in a guarded nested class. Failed unregister
still clears host lambdas and weak owners, and a revoked callback cannot report.
The bounded gate rejects old/foreign registration tickets and duplicate events
inside two seconds. It schedules no poller and stores no pixels.

The new request carries its originating session lease into the native request
queue. Withdrawn consent or changed authorization returns a local failure before
serialization. The Telegram request uses `reply_to_msg_id = 0`, because Android
does not provide a screenshot, region or message ID. Only real server Updates
are applied; no locally forged successful service message is added.

The inherited screenshot sender also now initializes the mandatory `reply_to`
field on its first send. Its existing message-ID guard and secret/media paths
are retained. Their runtime behavior remains an acceptance check.

Source preparation pins five composed hosts and six installed payloads. The
strict Java-8 gate probe passed 21 assertions; drift/collision/CRLF/installed-byte
checks passed. These do not execute the Android OS callback or Telegram service.
Full app compilation, pre-14 launch, real hardware screenshots and two-account
events remain unverified until separately recorded.

Primary references: [Android screenshot detection](https://developer.android.com/about/versions/14/features/screenshot-detection),
[Telegram screenshot service method](https://core.telegram.org/method/messages.sendScreenshotNotification).
