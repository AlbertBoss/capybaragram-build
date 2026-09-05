# CapybaraGram build experiments

This repository prepares initial Android and Windows builds from pinned Telegram sources. **It is not a CapybaraGram release or a working implementation of its planned features.** No successful full build has been recorded yet.

## Scope

- Android: offline ARM64 debug test, separate `org.capybaragram.buildtest.beta` application ID, no INTERNET permission, no usable Telegram API credentials, fresh debug signature. This verifies compilation and packaging before production configuration. It cannot exchange messages.
- Windows: official x64 debug executable using upstream restricted test API credentials. `TDESKTOP_API_TEST` does not select test data centers or disable networking. Do not use real accounts. Auto-update and crash reports are disabled; the updater is not packaged.

Both workflows run only when dispatched manually and only for public repositories. Standard `ubuntu-24.04` and `windows-2025` runners are used. No paid/larger runners, scheduled jobs, releases, shared caches or repository secrets are configured. Artifacts expire after one day. Standard public-runner execution is free under current GitHub rules; artifact storage remains quota-controlled. Do not enable paid overages.

## Sources and tooling

| Platform | Source revision | Build inputs |
|---|---|---|
| Android | [DrKLO/Telegram](https://github.com/DrKLO/Telegram/tree/62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c) | AGP 8.10.1, Gradle 8.11.1, JDK 17, SDK 36, build-tools 36.0.0, NDK 27.2.12479018, CMake 3.22.1 |
| Windows | [telegramdesktop/tdesktop](https://github.com/telegramdesktop/tdesktop/tree/80158983dba09d3bf5d96701f21473d6c34bf5f5) | VC 14.44, Windows SDK 10.0.26100.0, Python 3.10, Qt6 via upstream preparation, Ninja Multi-Config |

The Windows documentation mentions Visual Studio 2026. The current standard Windows runner lists VS2022 17.14; the workflow checks the actual VC toolset and uses the upstream-supported explicit Ninja generator. That compatibility still needs a real build. Dependency preparation invokes upstream scripts and can download substantial data; a source SHA does not pin all external downloads. Final application compilation is limited to two workers; upstream preparation contains its own parallel commands. Disk thresholds are preliminary safeguards, not proven resource requirements.

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
