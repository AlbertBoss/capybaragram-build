# Windows local vault foundation

This is a production-intended native component, not yet integrated with Telegram Desktop.

Each login must receive a persisted random generation from the host coordinator. Never derive a generation from a numeric account slot or reuse it on login, even for the same Telegram user. The store also binds encrypted records to the stable Telegram owner ID, generation and record identity. The host must check its account/lock epochs before queued operations and before showing results, and stop exposing the editor when the app locks or the session changes. Those host hooks are not implemented here yet.

Records use Windows DPAPI in current-user scope with UI forbidden. There is no machine-wide flag, cloud service, exported key or plaintext record on disk. This protects against other Windows users; it does not protect against another process running as the same Windows user or an administrator. App passcode gating still belongs to the host. Microsoft documents these boundaries in [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) and [CryptUnprotectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata). It is not a promise of hardware-backed keys or forensic erasure.

Writes encrypt before creating a unique temporary file, flush it, and replace the record within the same directory. Failure throws a generic error and must leave the editor open. A damaged record is preserved. Caller controls empty-note deletion; empty text is a valid binary payload at the storage layer. One record is capped at 131040 bytes. Strings are byte payloads; the UI adapter must enforce valid UTF-8 and its text limits.

Retirement writes a durable marker before deleting records. Reopening a retired generation fails even if cleanup was interrupted. The marker remains intentionally; cleanup may be retried. The host coordinator still needs durable active-generation metadata and cleanup scheduling. Creation is exclusive and cannot silently overwrite an existing generation.

Tests exercise the actual Windows APIs and filesystem with synthetic data, including owner/generation/record separation, tampering, reopen, locked-destination write failure, bounds, thread confinement, retirement and same-owner fresh generation. They do not establish Telegram UI, logout hook, passcode, real-account or final product acceptance. Native CI result pending.
