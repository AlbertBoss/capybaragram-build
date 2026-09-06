# Windows local vault foundation

This is a production-intended native component. Telegram Desktop source integration exists; full integration compilation and runtime acceptance remain pending.

Each login must receive a persisted random generation from the host coordinator. Never derive a generation from a numeric account slot or reuse it on login, even for the same Telegram user. The store also binds encrypted records to the stable Telegram owner ID, generation and record identity. The host must check its account/lock epochs before queued operations and before showing results, and stop exposing the editor when the app locks or the session changes. Worker implements the FIFO and lock/session epochs. Native Telegram source hooks are prepared separately; the UI and full integration compile remain pending.

Records use Windows DPAPI in current-user scope with UI forbidden. There is no machine-wide flag, cloud service, exported key or plaintext record on disk. This protects against other Windows users; it does not protect against another process running as the same Windows user or an administrator. App passcode gating still belongs to the host. Microsoft documents these boundaries in [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) and [CryptUnprotectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata). It is not a promise of hardware-backed keys or forensic erasure.

Writes encrypt before creating a unique temporary file, flush it, and replace the record within the same directory. Failure throws a generic error and must leave the editor open. A damaged record is preserved. Caller controls empty-note deletion; empty text is a valid binary payload at the storage layer. One record is capped at 131040 bytes. Strings are byte payloads; the UI adapter must enforce valid UTF-8 and its text limits.

Retirement writes a durable marker before deleting records. Reopening a retired generation fails even if cleanup was interrupted. The marker remains intentionally; cleanup may be retried. Registry supplies durable active-generation metadata and cleanup journals. Creation is exclusive and cannot silently overwrite an existing generation.

Tests exercise the actual Windows APIs and filesystem with synthetic data, including owner/generation/record separation, tampering, reopen, locked-destination write failure, bounds, thread confinement, retirement and same-owner fresh generation. They do not establish Telegram UI, logout hook, passcode, real-account or final product acceptance. The first Store revision passed native CI run 33984824455. Check exact source hashes in the separately recorded native verification; the registry changes require a new run.


## Persistent registry

Registry persists encrypted account-owner/generation bindings separately from the data records. A normal restart reopens the same generation. `freshLogin=true` retires it even when the Telegram owner is unchanged. The host must distinguish authorization restoration from a fresh login and call this method accordingly; those Telegram source hooks are prepared but not yet compiled into the client.

Logout records durable retirement intent before unlinking active bindings and deleting records. Failed cleanup remains queued for retry, and retired generations are never offered to the caller. Creation records a different journal type: a surviving creation journal with an active binding is committed and must preserve its data; an unreferenced creation is cleaned up. This distinction prevents a restart from destroying a successful save when only journal deletion was interrupted.

All registry/store operations run on one serialized worker. Host account and app-lock epochs must still reject stale operations and callbacks. `logout(slot, expectedOwner)` checks the stable owner, but the host must additionally ensure the request belongs to the current login generation, including same-owner relogin. Do not call this API from a stale UI callback.

The native registry tests use real DPAPI/files, reopen persistent state, isolate ten synthetic owners, inject interrupted journal phases, lock metadata/data files, and preserve malformed metadata without silent reset. They do not log into Telegram or prove its logout/passcode hooks.


## UI worker

Worker owns Registry/Store on one FIFO thread. A separate opaque handle identifies every live session, including same-owner relogin; stale detach cannot retire its replacement. Lock transitions invalidate requests and already-posted replies. UI callbacks capture a shared lifetime gate rather than a Worker pointer, so callbacks queued before shutdown are inert after destruction. The application adapter closes sensitive editors separately. Ordinary I/O errors produce a failed result; no plaintext/error details are logged.

Forgotten-passcode reset first writes an encrypted reset barrier, then retires every binding and retries pending cleanup. Reopening is blocked while cleanup remains incomplete. Worker invalidates every UI session immediately and retries a failed reset before accepting new storage. Tests use real Windows files and DPAPI, with synthetic owners and a controlled UI mailbox; they are not Telegram acceptance tests.

The preceding native proof covers the earlier Registry/Worker revision. The authorization identity changes require a new exact-source native test run and a Telegram integration durability check before release.

## Authorization identity

Registry CPGB2 bindings contain owner, authorization identity and generation. The Windows host generates a random 32-hex identity before constructing a fresh Telegram session and appends it to the same encrypted MTP authorization blob. Restoring that blob restores the same identity; a different identity retires the earlier generation even when owner is unchanged and freshLogin is false. Worker handles carry the identity through queued reads, writes and logout. This addresses a restart between a persisted new Telegram login and queued vault replacement.

Pre-Capy authorization blobs and CPGB1 bindings use a stable reserved all-zero identity. They are not reset merely by upgrading. A malformed trailer disables vault attachment without silently creating a replacement identity. Invalid Registry identities are rejected before changing the data; stale logout identities cannot delete a different authorization's notes. The trailing marker is local storage metadata and is never sent to Telegram.

Native tests cover changed/same identity restoration, stale logout, invalid identity preservation, locked binding replacement, CPGB1 migration and malformed CPGB2 metadata. These are real DPAPI/filesystem tests with synthetic owners. Native client serialization round-trip, forced-stop integration, and real account acceptance still need verification. Downgrading to a client without this extension is not supported for the new metadata.
