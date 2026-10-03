# Offline voice transcription — development module

This module is not yet part of a CapybaraGram APK or EXE. It contains an actual
CPU Whisper engine, Android JNI, a local MediaCodec audio decoder, one-use
cancelable jobs and a hash-pinned model downloader. Client menus, account/session
lifecycle gates, encrypted temporary input, message download handling and Windows
audio decoding remain to be integrated before this is a usable client feature.

Source: ggml-org/whisper.cpp v1.9.4, commit and archive digest in source-pins.json.
All 1,959 Git blobs were verified locally before review. Upstream MIT notice is
included. This establishes source identity, not an exhaustive security audit.
The reviewed path disables server, CURL, RPC, dynamic backends and GPU backends.
The multilingual tiny model is about 78 MB; download is explicit, HTTPS-only,
bounded and checked by exact SHA-256 before installation. A model check never
accepts a file merely by name. No audio is uploaded by this module.

Limits: three minutes per job, at most two CPU threads in the Android adapter,
PCM16/float decoding at 8–48 kHz with one or two channels, 16 kHz mono engine input.
Every message gets a new context; old transcript context is not reused. UI must
cancel on logout, lock, account/chat switch and destruction, and discard stale
results. Native handle release is worker-only and synchronized with cancellation.
UTF-8 filesystem handling supports Cyrillic Windows paths in the engine.

The manual native workflow builds/runs actual CPU recognition on Linux and Windows
with the upstream JFK fixture, checks cancellation and input rejection, and
cross-compiles Android ARM64 JNI. It does not verify Russian accuracy, codec
runtime, real Telegram behaviour, resource use on the owner's machine or packet
capture. Those remain explicit acceptance tasks.
