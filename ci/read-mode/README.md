# Android silent-read integration — draft, not shipped

`ReadReceiptPolicy.java` owns mode and one-use permissions per account session. Requests captured while silent remain suppressed after disabling the mode. A queued request captured before enabling the mode is also suppressed if it reaches the gate while silent. Reset invalidates old-session tickets.

`CapyReadReceipts.java` binds tickets to exact TLObject identity, account, owner and session object. Preferences are account-local and additionally keyed by owner ID. Logout retires the session before host cleanup. Explicit requests never grant permission to an unrelated request. Scope is message read receipts, not online/typing/story invisibility.

`prepare_android_read_mode.py` is prepared to run after the existing accounts, notes and folder-callback transforms. It patches ConnectionsManager, MessagesController, UserConfig, ChatActivity and the previously added CapyVault lifecycle adapter. It captures request state before the network queue, completes suppressed requests with a local error (no synthetic successful server response), and avoids creating delayed read tasks while silent. The secret-chat media-read guard preserves the existing local TTL task; deleted-message retention is a different, unfinished feature.

Local tests executed: 21 policy checks, 51 host-adapter checks and 52 request-factory checks. Cases include ten accounts, exact request identity, stale UI owner, logout/relogin, concurrent ticket consumption, host-lock interaction, ordinary/channel/thread/monoforum/secret routing and correct acknowledgement types. Adapter tests stub Android host/preferences/TL objects; request tests use three exact DialogObject methods from pinned source. Eight TL class names were verified in pinned TLRPC source. Five transformed host files and six added files passed byte/hash checks. These are not a full client compile or end-to-end acceptance.

Native toggle and explicit read dialog code now exists in CapyReadModeUi; ChatActivity exposes menu ID9003 in normal non-preview chats. Manual read targets the latest message loaded when the dialog opened, using minMessageId[0], threadMessageId and maxDate[0]; it does not claim all unseen history was loaded. UI and responses retain account/session/chat identity. Dialogs close on pause, destruction, app lock and owner change. Full Android compilation and visual acceptance remain pending.

The host owner field is made volatile and read directly by the synchronized bridge, avoiding an inverse lock order with UserConfig.setCurrentUser. A bounded two-thread fixture test verifies bridge reads finish while the host owner lock is held; this is not an explanation for an earlier installed-client freeze, because this draft is not installed.

The manual Android candidate workflow now prepares this draft and runs the policy/adapter/request tests before the full APK build. It is not part of any previously verified APK. Remaining before feature acceptance:

- Compile and exercise native toggle, confirmation, cancellation, app lifecycle and explicit read callbacks in the actual client.
- Full read-path review, especially secret-chat service messages, scheduled operations, cancellation and callbacks; decide expected handling of mentions/reactions/stories separately.
- Production compilation and tests using actual request callbacks, then end-to-end read receipt checks using owned test accounts.
- Windows equivalent, complete deleted-message history and secret-chat requirements remain in scope.

Do not mark the feature implemented in release notes or ship these helpers alone. Do not recreate timers; the user starts goal work with Play.
