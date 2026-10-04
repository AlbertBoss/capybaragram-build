# Android local message archive

Opt-in per Telegram account; disabled by default. A native chat-menu entry enables
capture and reads the archive for that chat. Existing messages are captured only
when an observed deletion, media-expiry or edited-message replacement occurs. Once/TTL viewer entry also captures before playback/display; viewer closing retries the same account generation if the original became available later.

The Telegram storage queue waits for the separate archive worker to commit before
continuing the original mutation. Disk/key failures do not block Telegram deletion;
a sanitized diagnostic records the failure. This is not recovery from the server.

Snapshots contain encrypted text and serialized Telegram message data. Full downloaded photo/document files can now be copied before the mutation. The highest real photo size is required: a thumbnail, partial file or unavailable source is never labelled as an original. This includes the encrypted-cache format when its exact 48-byte key and declared file size are available. Each 64 KiB chunk and the final size, MIME and SHA-256 descriptor are AES-GCM authenticated. No source file is modified or fetched from the server. Secret-chat text/media uses the same observed storage paths; live secret-chat, TTL and one-view acceptance is pending.
Topic-specific filtering and an archive list for removed dialogs are pending.

AES-GCM authenticates account generation, row identity and payload purpose. Keys
use AndroidKeyStore; storage is in private no-backup files. SQLite metadata
(dialog/message identifiers and capture time) remains visible inside the private
app directory. No claim of full-database encryption or rollback prevention.
Limits: 2,000 snapshots per account, 60,000 serialized bytes per message, 20 entries per page; 32 MiB per original and 128 MiB total authenticated attachment storage. Quota uses actual encrypted bytes, including overhead. Oldest originals may be pruned while their text snapshots remain. Schema v1 migrates additively to v2 without replacing snapshot ciphertext or key. Unsupported versions are preserved. Disabling retains data; archive clearing
retires its key/database without signing out. Logout retires the account generation.

Preparation composes six pinned native source files after account, note,
read-mode and appearance changes. Test classes and the standalone test manifest
are not in the production-file allowlist. The full Android candidate workflow
compiles the native chat UI and hooks. The manually dispatched runtime workflow
checks actual Android SQLite, Keystore, reopening, duplicate events, pruning,
account isolation, lock behaviour, stale work and clearing with synthetic data.
A passing standalone test does not prove live Telegram behaviour.

The archive page exposes attachment buttons. Image previews are sampled to at most two million pixels; audio/video use Android MediaPlayer with a bounded in-memory MediaDataSource. Plaintext media is not written to disk or passed to external apps. Lock, logout, account/location changes or closing the dialog release playback and wipe the buffer; stale worker results are also disposed. Other file formats are stored but their preview/export is not implemented.

V2 backend and instrumented checks compile against Android API 36. Run 37166315419 passed actual V2 SQLite/AndroidKeyStore checks on the API 30 emulator, including complete original roundtrip, quota and V1 migration. The eight source digests of that earlier revision were verified. Full Telegram compilation is now verified in APK 37170920572; live native viewer/secret/once scenarios remain pending. Tests now cover multi-chunk roundtrip, incomplete/extra input rollback, ciphertext tampering, missing chunks, maximum-file quota, cascade cleanup, unchanged V1 ciphertext migration, and encrypted-input read ranges. The standalone decrypt callback test does not establish Telegram native AES-CTR integration.

Early viewer capture is now hooked into SecretMediaViewer and SecretVoicePlayer. The UI serializes a bounded message snapshot and holds a source descriptor before the native consume callbacks. A separate FIFO encrypts/copies the original; at most four viewer snapshots are pending/active. Descriptors close and copied TL bytes are wiped on success, failure, overflow and stale owner/generation. The closing retry reuses the token captured at opening, so a logout/slot reuse cannot rebind an old viewer to the new account. The descriptor is held before the native callback; encryption commits later on the worker. A process crash before commit can still lose this capture. Admission requires the archive setting and an unlocked application; an already admitted background snapshot may finish after disabling or locking, while new viewer admissions stop. Clearing/logout invalidates the generation. No read/listen RPC or extra playback is invoked by archive capture. These new hooks compile in APK 37170920572; live once/TTL/secret scenarios remain pending.

The previous V2 client APK (37167432589) compiled and passed signer/class/JNI/notice inspection. New runtime checks also exercise an open descriptor after source unlink, nonblocking UI enqueue, bounded overflow rejection, stale-generation cleanup and operation-failure cleanup. Run 37170895734 passed these checks on the API 30 emulator. Its artifact digest and all eight tested source hashes were verified locally. This verifies the standalone archive/source/coordinator path with synthetic data, not the native viewer lifecycle with a live Telegram peer. Full APK run 37170920572 succeeded; local inspection verified SHA-256, persistent signer, 23 production integration definitions, ARM64 JNI 16 KiB alignment and embedded/package MIT notice. Live once/TTL/secret acceptance remains separate.
