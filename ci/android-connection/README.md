# Android connection transport — development stage

This separate package adapts the bounded, pinned `ci/connection` MTProto tunnel
to Android. The existing Windows core and its verified files are unchanged.

It uses Rustls **0.23.45**, rustls-webpki **0.103.15**, ring **0.17.14**,
webpki-roots **1.0.9** and the already pinned tokio-tungstenite **0.24.0**.
An explicit ring provider and bundled public roots replace system OpenSSL.
The Telegram URI hostname remains the TLS verification name and SNI even
when TCP connects to a pinned Telegram IP. Certificate checks are never disabled.
Private/enterprise roots are not imported from Android automatically. Root updates
require an application update.

`prepare_android_core.py` verifies the 24-file proven base and its 17-file
prepared manifest before applying the Android changes. It validates every payload
and transformation before writing a fresh destination. Production preparation
requires a reviewed, checksummed Android `Cargo.lock` and cannot resolve dependencies.

The explicitly named manual `android-connection-lock.yml` workflow is a one-off
development job to generate that lock, run actual TLS acceptance/rejection tests,
run the preserved core tests and native C ABI probe, and cross-compile JNI for
ARM64 and x86_64 with NDK **27.2.12479018**, API **23** and 16 KiB page alignment.
It has read-only repository permissions, no owner API keys or signing certificate,
and produces logs/metadata rather than an APK. There is no timer or scheduled trigger.

`NativeTunnel.java` / `android_jni.cpp` expose only start, status and stop, using
opaque never-reused handles. The 36-byte endpoint is process-local: port plus a
random MTProto token. JNI validates sizes/ABI, wipes its temporary token copies
and stops a started listener if delivery to Java fails. Calling code must start
and stop on a worker thread and wipe its endpoint copy. No Telegram account keys
are passed to this bridge; no arbitrary SOCKS forwarding or external Worker is enabled.

At creation, no Android native compilation or runtime is claimed. This package
is not yet connected to the Telegram Android settings, login or account manager.
No live Telegram connection, VPN transition, Android emulator JNI execution or
real-device acceptance has been performed. These are separate gates before release.

Primary security references (checked 2026-10-04):

- [Rustls TLS boundary fix, patched in 0.23.45](https://rustsec.org/advisories/RUSTSEC-2026-0285.html)
- [WebPKI CRL parser fix, patched in 0.103.13](https://rustsec.org/advisories/RUSTSEC-2026-0104.html)
- [WebPKI URI name constraints fix, patched in 0.103.12](https://rustsec.org/advisories/RUSTSEC-2026-0098.html)
- [WebPKI wildcard constraints fix, patched in 0.103.12](https://rustsec.org/advisories/RUSTSEC-2026-0099.html)
- [WebPKI CRL scope fix, patched in 0.103.10](https://rustsec.org/advisories/RUSTSEC-2026-0049.html)
- [Ring AES panic fix, patched in 0.17.12](https://rustsec.org/advisories/RUSTSEC-2025-0009.html)

These selected advisory checks are not a full dependency or client security audit.
Registry checksums and declared licenses for the new TLS dependencies are stored
in `source-provenance.json`; final license notices and the complete frozen lock
inventory must accompany a redistributed APK.

## Confirmed native compilation, 2026-10-04

[37192578101](https://github.com/AlbertBoss/capybaragram-build/actions/runs/37192578101)
passed 90 Rust tests including the actual TLS/WebSocket certificate checks, Clippy
with warnings as errors and 632 actual C++ ABI assertions. JNI compiled for both
ARM64 and x86_64 with verified 16 KiB ELF load alignment and system-only imports.
The frozen lock and 12 package hashes were independently verified. Its 111 registry
versions had no OSV database matches at the recorded check time; this is not a
source audit. The initial synthetic server omitted the binary WebSocket response
subprotocol; its fixture was corrected without weakening certificate validation.

The newly added `android-connection-device.yml` is a separate manual gate for
actual JNI execution in an isolated API 30 emulator, including boundary rejection,
independent listeners, repeated shutdown and stale handles. It uses only synthetic
loopback traffic and a disposable test signer. It does not test Telegram login,
real providers, VPN transitions or production ARM64 execution. Client integration
remains pending. Actual API 30 JNI execution subsequently passed as recorded below.

## Confirmed API 30 JNI execution, 2026-10-04

[37193035153](https://github.com/AlbertBoss/capybaragram-build/actions/runs/37193035153)
passed actual JNI execution on an isolated Android 11 x86_64 emulator. Its checks
cover invalid/null array bounds, ABI readiness, two independent listeners/tokens,
SOCKS rejection by connection closure, independent/idempotent shutdown, stale
handles, wiping failed status output and repeated start/stop without handle reuse.
The 427 assertions include repeated hexadecimal byte validation, not 427 separate
user scenarios. The native 90 Rust tests and 632 C++ ABI assertions also passed.
The artifact, all 15 package hashes and the executed JNI binary identity were
independently verified. No owner keys or accounts were used. No live Telegram
connection, production ARM64 execution or VPN transition is claimed.

## Native client integration prepared, 2026-10-04

The package now includes the native login/chat controls, a bounded Java controller
and a memory-only native proxy coordinator. The first full application build is
pending. These Java changes preserve the frozen Rust/JNI source and native proofs
above; those earlier runs do not prove this new client integration.

The controller has 27 locally executed assertions (including 2,000 coalesced
requests), the route coordinator has 24 and guarded source preparation has ten.
All controller/route tests use synthetic engine/native targets, not an authenticated
Telegram client. See [the integration notes](../../docs/ANDROID-CONNECTION.md)
for the lock ordering, manual-proxy revocation, initialization race, controls and
remaining acceptance and licensing gates.
