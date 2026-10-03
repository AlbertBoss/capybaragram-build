# Android local message archive

Opt-in per Telegram account; disabled by default. A native chat-menu entry enables
capture and reads the archive for that chat. Existing messages are captured only
when an observed deletion, media-expiry or edited-message replacement occurs.

The Telegram storage queue waits for the separate archive worker to commit before
continuing the original mutation. Disk/key failures do not block Telegram deletion;
a sanitized diagnostic records the failure. This is not recovery from the server.

Snapshots contain encrypted text and serialized Telegram message data. Original
photo/video/voice files are **not yet copied**. Secret-chat text uses the same
observed storage paths, but live secret-chat, TTL and one-view acceptance is pending.
Topic-specific filtering and an archive list for removed dialogs are pending.

AES-GCM authenticates account generation, row identity and payload purpose. Keys
use AndroidKeyStore; storage is in private no-backup files. SQLite metadata
(dialog/message identifiers and capture time) remains visible inside the private
app directory. No claim of full-database encryption or rollback prevention.
Limits: 2,000 snapshots per account, 60,000 serialized bytes per message, 20 entries
per page. Oldest snapshots are pruned. Disabling retains data; archive clearing
retires its key/database without signing out. Logout retires the account generation.

Preparation composes four pinned native source files after account, note,
read-mode and appearance changes. Test classes and the standalone test manifest
are not in the production-file allowlist. The full Android candidate workflow
compiles the native chat UI and hooks. The manually dispatched runtime workflow
checks actual Android SQLite, Keystore, reopening, duplicate events, pruning,
account isolation, lock behaviour, stale work and clearing with synthetic data.
A passing standalone test does not prove live Telegram behaviour.
