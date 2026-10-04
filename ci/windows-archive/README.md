# Windows local archive: storage, worker and native integration

Storage and its account-bound worker have passed synthetic native Windows tests.
The source recipe now connects opt-in settings, chat/topic archive UI and native
edit/delete/expiry hooks. **That native client integration has not yet been compiled
or accepted with a live Telegram peer.** It is not yet in a downloadable archive
client. Secret-chat protocol support is not provided by the pinned official
Desktop base or this package.

`archive_store` borrows a serialized `Capy::Vault::Store`. The native recipe uses an independent `tdata/capybara-archive` account registry, with the existing
owner/authorization/generation binding, rather than the notes registry. The
snapshot records typed peer, topic, message, timestamps, reason, bounded UTF-8
text and versioned adapter metadata. Metadata is **not raw Telegram TL**.

## Persistence and bounds

- Every snapshot, catalog and original media chunk uses current-user Windows
  DPAPI with owner, generation and record identity as additional entropy. This
  does not isolate data from hostile software running as the same Windows user.
- Up to 2,000 rows; pages contain at most 20 opaque random identifiers.
- Text and adapter metadata: at most 60,000 bytes each, 120,000 combined.
- Complete original media: at most 32 MiB, in 64 KiB chunks. No plaintext file is
  created. The reader must return the exact declared length; short and oversized
  sources fail. An unavailable original remains explicitly unavailable.
- SHA-256 is stored inside the protected snapshot. Reads authenticate all chunks
  and verify the full original before returning it to an in-memory consumer.
- Steady-state ciphertext quota: at most 128 MiB. Catalog size is reserved
  conservatively at 70,000 bytes during admission; all entry/chunk sizes are actual
  ciphertext file sizes. During an atomic replacement, old records coexist with
  one staged capture, adding at most approximately 32 MiB plus record overhead.

Chunks and snapshot are written first; the encrypted catalog is atomically
replaced last. A failed catalog replacement leaves the previous archive intact.
After a successful commit, unreferenced old/staged records and strict archive
temporary files are removed. Failed cleanup is reported by `Added.cleanupPending`
and blocks further access until `recover()` succeeds. Do not retry `add()` after
such a result: its catalog entry already committed.

Recovery validates **every catalog reference before deletion**. Missing, damaged,
unknown-version catalogs, malformed records, missing chunks or reparse files fail
without silently recreating the archive. A catalog is initialized only for an
empty namespace. No archive clear API bypasses registry retirement; the account-bound worker
revokes old operations and retires its archive generation before later access.

## Verification boundary

The manually dispatched `windows-archive-runtime.yml` compiles with MSVC `/W4 /WX`
and uses actual DPAPI and Win32 file operations on synthetic data. It also reruns
the unchanged vault, account registry and worker runtime suites to cover the new
strict archive key namespace. Results must be inspected before marking this stage
verified. No scheduled execution, owner secrets, real Telegram accounts or paid
services are used by this workflow.

Storage and retained-original runtime passed in
[37173494718](https://github.com/AlbertBoss/capybaragram-build/actions/runs/37173494718)
at `d2d7bfa3e9ee9265bbf490c731947d87996de1c1`: archive 72 assertions,
vault 240, registry 94, worker 58. Artifact SHA-256 and all 14 tested source
hashes were independently checked after download. This includes actual deleted
file handle streaming and does not include native Telegram integration. Reparse
rejection is implemented; a junction/symlink runtime fixture is still pending.

The guarded `prepare_windows_archive.py` applies after the read-mode and voice
recipes. It binds 17 normalized native host hashes (14 modified and 3 unchanged decoder
safety dependencies) and 14 module hashes, validates
all inputs before writing and refuses changed sources or existing module files.
The adapter captures existing text before server edits/deletion notifications,
before TTL destruction and before original cache cleanup. It also captures at
the native timed-media viewer / TTL voice-round layer entry. Matching document
bytes or exact Large photo bytes are retained in owned memory; completed native
file locations use a verified held file handle. It does not download missing
originals or substitute thumbnails. Limits/failed admission produce an explicit
record without a media copy; repeated early/final TTL snapshots are not deduplicated
yet. The UI supports chat/topic paging, account opt-in, account archive clear and
bounded static image preview. The native player source adds original audio/video
(including round video) playback from a QBuffer through Streaming::Reader/Player,
pause/replay and ten-second seeking. Closing the preview permanently stops its
player and releases its reader before layer fade-out. No real DocumentData,
MTProto loader, plaintext temporary file or native download cache is modified.
Full C++ compilation, actual speakers and live UI acceptance remain pending.

Application/account wiring uses an independent registry, the same authorization
identity, per-account settings, passcode lock/unlock and logout/forgotten-passcode
revocation. Full MSVC client compilation, restart tests and live peer acceptance
are pending. Secret-chat protocol support remains a required separate part of P2.

`VerifiedInput` admits an already complete, unencrypted original inside an explicit
trusted local root, with its exact declared length. It rejects reparse ancestors,
hard links, directories, device/ADS/ambiguous paths, root-prefix siblings, oversized
and missing files. It holds a Win32 read handle that permits deletion but denies
new writes; the worker streams that handle instead of reopening a mutable path.
This is not a decryptor for Telegram's encrypted cache or a downloader of absent
originals. Native media selection and ownership gates remain pending.

## Account-bound worker

`archive_worker` owns an independent archive Registry on one serialized worker.
Newly attached handles default to capture disabled; the host supplies each
account's persisted opt-in. Foreground requests are limited to eight. The burst
revision separates four media
captures from up to 2,000 lightweight text snapshots, with at most 64 MiB of
queued text/metadata. Rejecting an admission releases its owned reader.
Readers must capture owned resources such as `shared_ptr<VerifiedInput>`.

Per-session live/revision checks stop queued or streaming work after logout,
replacement or archive clear. `clear()` revokes old results before asynchronously
retiring the archive generation; it does not clear the notes registry. Failed
retirement/recovery is retried before later access. Already admitted encrypted
captures may finish on passcode lock or disabling capture; new captures require
opt-in. Incoming opt-in captures may run while locked, without exposing content.
Foreground reads and posted callbacks require the unchanged unlocked UI epoch.
Callbacks cannot dereference a destroyed Worker.

The worker runtime below is verified. Application/account lifecycle wiring,
persisted opt-in and native message adapters are now connected in source, with
full client compilation and live acceptance still pending.

The account-bound worker, typed-chat filtering and burst revision passed in
[37175109886](https://github.com/AlbertBoss/capybaragram-build/actions/runs/37175109886):
archive 82 assertions, archive worker 337, plus the existing vault suites.
All 17 source hashes and the artifact digest were independently verified.
The worker suite took 462 ms on the CI machine. Cached ciphertext
weights replace repeated full-archive decryption on append; the authenticated
catalog is still checked before access, and recovery rebuilds/verifies all
weights. A changed or damaged catalog is rejected even in an already open store.
The synthetic worker receipt records total elapsed time on its CI machine;
this is not a weak-PC or native Telegram performance benchmark.

API basis: [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
and [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).

Native references: [pinned Telegram Desktop source](https://github.com/telegramdesktop/tdesktop/tree/80158983dba09d3bf5d96701f21473d6c34bf5f5/Telegram/SourceFiles),
[Qt QByteArray ownership](https://doc.qt.io/qt-6/qbytearray.html) and
[Qt implicit sharing](https://doc.qt.io/qt-6/implicit-sharing.html). The adapter
retains its own media resources rather than borrowing a view that can be cleared.

The actual Qt setting codec passed 29 assertions on Windows/Qt 6.11.2 in
[37177292930](https://github.com/AlbertBoss/capybaragram-build/actions/runs/37177292930).
The artifact digest and all three tested source hashes were independently checked.
This GCC/test-only MSYS2 Qt result covers boolean round trips, missing/truncated
tails and unknown tags/versions/values; it does not prove native account restart
or full MSVC client compilation. The full build separately compiles/runs the same
codec against production Qt before compiling Telegram.

The memory player uses the pinned native FFmpeg path, whose exact
`RestrictToCustomIO` function sets an empty protocol whitelist before opening
input. The preparation binds that function, its native streaming caller and
QBuffer loader source. A manually dispatched decoder policy probe embeds the
exact pinned function (preserving its upstream notice), decodes synthetic Opus,
AAC and H.264, and exercises file/HTTP playlist references with allowed and
denied controls. Its result is separate from full client/player UI acceptance.
