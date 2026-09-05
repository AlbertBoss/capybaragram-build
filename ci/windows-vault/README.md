# Windows local vault foundation

This is a production-intended native component, not yet integrated with Telegram Desktop.

Each login must receive a persisted random generation from the host coordinator. Never derive a generation from a numeric account slot or reuse it on login, even for the same Telegram user. The store also binds encrypted records to the stable Telegram owner ID, generation and record identity. The host must check its account/lock epochs before queued operations and before showing results, and stop exposing the editor when the app locks or the session changes. Those host hooks are not implemented here yet.

Records use Windows DPAPI in current-user scope with UI forbidden. There is no machine-wide flag, cloud service, exported key or plaintext record on disk. This protects against other Windows users; it does not protect against another process running as the same Windows user or an administrator. App passcode gating still belongs to the host. Microsoft documents these boundaries in [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) and [CryptUnprotectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata). It is not a promise of hardware-backed keys or forensic erasure.

Writes encrypt before creating a unique temporary file, flush it, and replace the record within the same directory. Failure throws a generic error and must leave the editor open. A damaged record is preserved. Caller controls empty-note deletion; empty text is a valid binary payload at the storage layer. One record is capped at 131040 bytes. Strings are byte payloads; the UI adapter must enforce valid UTF-8 and its text limits.

Retirement writes a durable marker before deleting records. Reopening a retired generation fails even if cleanup was interrupted. The marker remains intentionally; cleanup may be retried. The host coordinator still needs durable active-generation metadata and cleanup scheduling. Creation is exclusive and cannot silently overwrite an existing generation.

Tests exercise the actual Windows APIs and filesystem with synthetic data, including owner/generation/record separation, tampering, reopen, locked-destination write failure, bounds, thread confinement, retirement and same-owner fresh generation. They do not establish Telegram UI, logout hook, passcode, real-account or final product acceptance. The first Store revision passed native CI run 33984824455. Check exact source hashes in the separately recorded native verification; the registry changes require a new run.


## Persistent registry

Registry persists encrypted account-owner/generation bindings separately from the data records. A normal restart reopens the same generation. `freshLogin=true` retires it even when the Telegram owner is unchanged. The host must distinguish authorization restoration from a fresh login and call this method accordingly; those Telegram hooks are still pending.

Logout records durable retirement intent before unlinking active bindings and deleting records. Failed cleanup remains queued for retry, and retired generations are never offered to the caller. Creation records a different journal type: a surviving creation journal with an active binding is committed and must preserve its data; an unreferenced creation is cleaned up. This distinction prevents a restart from destroying a successful save when only journal deletion was interrupted.

All registry/store operations run on one serialized worker. Host account and app-lock epochs must still reject stale operations and callbacks. `logout(slot, expectedOwner)` checks the stable owner, but the host must additionally ensure the request belongs to the current login generation, including same-owner relogin. Do not call this API from a stale UI callback.

The native registry tests use real DPAPI/files, reopen persistent state, isolate ten synthetic owners, inject interrupted journal phases, lock metadata/data files, and preserve malformed metadata without silent reset. They do not log into Telegram or prove its logout/passcode hooks.
