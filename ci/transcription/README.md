# Offline voice transcription — development module

The Android candidate pipeline now includes native voice menus and the engine;
APK run 37164244121 compiled successfully; its signature, 20 integration class definitions and 16 KiB-aligned ARM64 JNI were checked. The Windows client UI is pending.
The module contains an actual
CPU Whisper engine, Android JNI, a local MediaCodec audio decoder, one-use
cancelable jobs and a hash-pinned model downloader. Android menu/UI gates capture the account generation and close/cancel on chat
pause, destruction, logout or app lock. Only already-downloaded voice messages
are decoded; encrypted cache files and one-view media need a separate adapter.
No plaintext temporary audio file is created. Windows audio/UI integration and
actual Android client acceptance remain necessary.

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
cross-compiles Android ARM64 JNI. Run 37163441147 passed actual recognition on Linux/Windows and Android JNI
compilation for the first engine. This does not verify Russian accuracy, codec
runtime, real Telegram behaviour, resource use on the owner's machine or packet
capture. Those remain explicit acceptance tasks.

A separate manually dispatched Android speech runtime workflow now compiles the same JNI for x86_64 and runs the actual MediaExtractor/MediaCodec decoder and CPU recognizer on an ephemeral API 30 emulator. It creates Opus mono and AAC 44.1 kHz stereo fixtures from the pinned upstream JFK sample. The test APK has no Internet permission or shared UID; model bytes and fixture digests are checked before use. It also checks cancellation, UI-thread rejection, malformed audio and one-use jobs. Test classes, fixtures and test model are excluded from the production APK. Run 37166655634 passed all 14 actual Android checks on the API 30 x86_64 emulator. The artifact digest, exact Java/native source digests, pinned model and runtime report were verified. This English fixture does not establish Russian accuracy, ARM64 execution or live Telegram UI acceptance. Production JNI installation continues to require ARM64.
