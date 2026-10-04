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
