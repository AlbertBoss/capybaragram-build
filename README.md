# CapybaraGram build experiments

This repository prepares initial Android and Windows builds from pinned Telegram sources. **It is not a CapybaraGram release or a working implementation of its planned features.** The complete offline Android workflow succeeded in [run 33969421213](https://github.com/AlbertBoss/capybaragram-build/actions/runs/33969421213): compilation, manifest/signature/ARM64 checks and artifact upload passed. Installation and runtime testing remain pending.

## Scope

- Android: offline ARM64 debug test, separate `org.capybaragram.buildtest.beta` application ID, no INTERNET permission, no usable Telegram API credentials, fresh debug signature. This verifies compilation and packaging before production configuration. It cannot exchange messages.
- Windows: official x64 debug executable using upstream restricted test API credentials. `TDESKTOP_API_TEST` does not select test data centers or disable networking. Do not use real accounts. Auto-update and crash reports are disabled; the updater is not packaged.

All workflows run only when dispatched manually and only for public repositories. Standard `ubuntu-24.04` and `windows-2025` runners are used. No paid/larger runners, scheduled jobs, releases or shared caches are configured. Artifacts expire after one day. Standard public-runner execution is free under current GitHub rules; artifact storage remains quota-controlled. Do not enable paid overages.

Each platform has its own concurrency group. Android and Windows may run together; multiple builds of the same platform stay serialized without canceling an active build.

## Android online preview preparation

`android-preview.yml` prepares a separate `org.capybaragram.preview.beta` ARM64 debug app with owner API credentials and persistent signing. Its online CI run succeeded; installation and login remain unverified. It shares the Android concurrency group. Four repository Actions Secrets are required: `CAPY_API_ID`, `CAPY_API_HASH`, `CAPY_ANDROID_KEYSTORE_BASE64`, and `CAPY_ANDROID_KEYSTORE_PASSWORD`. The PKCS12 alias is `capybaragram-preview`; its public certificate SHA256 is pinned in the workflow. Missing inputs or a different signer stop the job.

Credentials and signing passwords enter the relevant steps through the environment. Only the verified APK, checksums and notices are uploaded; do not upload source with embedded API credentials, build intermediates or signing material. GitHub Secrets does not make an application API ID/hash unextractable from a distributed APK. It is separate from a user's Telegram login/session.

Local checks cover preparation, synthetic APK acceptance/rejection, and actual JDK restoration/certificate verification of the persistent key. They do not prove a working Telegram client, support for 10 accounts, folder synchronization, notifications or other planned features.

## Verified builds and Windows preview preparation

The [Android online preview run 33972555759 succeeded](https://github.com/AlbertBoss/capybaragram-build/actions/runs/33972555759), including APK package, INTERNET, signer and native ABI checks. The downloaded archive and APK checksums also passed locally; installation and login remain unverified. 

The [Windows baseline run 33964398564 succeeded](https://github.com/AlbertBoss/capybaragram-build/actions/runs/33964398564). Downloaded archive/EXE checksums and x64 PE headers passed locally. The actual launch remains unverified; baseline toolchain compatibility is now demonstrated.

`windows-preview.yml` uses the same toolchain with owner API credentials from an initial CMake cache outside the source/artifacts. Eight pinned source files separate the default profile (`APPDATA/CapybaraGram Preview`), portable folder (`CapybaraGramForcePortable`), IPC ID, notification activator, shortcuts and application identity. Automatic legacy Telegram data migration and automatic URL association registration are removed; manual URL association settings remain available. The collected executable is `CapybaraGram.exe`. The online Windows workflow has not yet passed a native build or runtime check. No paid code-signing certificate is configured.

Ten source-contract tests cover identity separation, preservation of Windows system GUIDs and license headers, preparation/verification and rejection of changed inputs. They cannot prove runtime profile isolation. Before real account use, verify launch beside official Telegram, both profile paths, notifications, shortcuts, restart and manual link association behavior.

## Sources and tooling

| Platform | Source revision | Build inputs |
|---|---|---|
| Android | [DrKLO/Telegram](https://github.com/DrKLO/Telegram/tree/62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c) | AGP 8.10.1, Gradle 8.11.1, JDK 17, SDK 36, build-tools 36.0.0, NDK 27.2.12479018, CMake 3.22.1 |
| Windows | [telegramdesktop/tdesktop](https://github.com/telegramdesktop/tdesktop/tree/80158983dba09d3bf5d96701f21473d6c34bf5f5) | VC 14.44, Windows SDK 10.0.26100.0, Python 3.10, Qt6 via upstream preparation, Ninja Multi-Config |

The Windows documentation mentions Visual Studio 2026. The current standard Windows runner lists VS2022 17.14; the workflow checks the actual VC toolset and uses the upstream-supported explicit Ninja generator. The baseline CI build demonstrated that compatibility. Dependency preparation invokes upstream scripts and can download substantial data; a source SHA does not pin all external downloads. Final application compilation is limited to two workers; upstream preparation contains its own parallel commands. Disk thresholds are preliminary safeguards, not proven resource requirements.

Official Actions revisions are recorded in `action-pins.json`; the action metadata was read, but this is not a full audit of their bundled dependencies.

## Run and acceptance

1. Publish this reviewed build-only directory to a public repository after owner approval. Do not upload the separate project research folder, local machine report, Telegram materials or model conversations.
2. Dispatch one platform workflow. Keep paid usage disabled. Record the first actual resource or compilation failure and fix it before retrying; do not blindly rerun repeatedly.
3. A green workflow must produce the expected executable/APK and checksums. Android collection rejects an unexpected package, INTERNET permission, signature failure or wrong ABI.
4. Install and launch test artifacts in a disposable test environment, then record runtime dependencies and errors. These checks have not been performed.
5. Replace temporary baseline configuration with reviewed production identifiers, owner API credentials, signing/update infrastructure, original graphics and the actual product changes. Verify real account login, message/media exchange, notifications, calls and updates on both platforms before any client release.

Generated debug keys intentionally change between runs; bit-for-bit reproducibility is not claimed.

## License

New orchestration scripts are MIT-licensed. Telegram source and derived binaries retain their upstream licenses (Android GPL-2.0, desktop GPL-3.0 and applicable exceptions/third-party notices). This repository's MIT license does not relicense Telegram. Distributing derived binaries requires the corresponding source and license obligations to be fulfilled, including local modifications.

## Evidence

- [Windows build instructions at the selected SHA](https://github.com/telegramdesktop/tdesktop/blob/80158983dba09d3bf5d96701f21473d6c34bf5f5/docs/building-win.md)
- [Windows upstream workflow at the selected SHA](https://github.com/telegramdesktop/tdesktop/blob/80158983dba09d3bf5d96701f21473d6c34bf5f5/.github/workflows/win.yml)
- [GitHub runner image inventory](https://github.com/actions/runner-images/blob/main/images/windows/Windows2025-Readme.md)
- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- `workflow-validation.json`: local syntax/constraint validation only, not compilation.
