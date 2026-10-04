# Windows local archive: storage stage

This package implements storage, **not the Telegram UI or message lifecycle adapter**.
It is not yet part of a downloadable Windows client. Secret-chat support is not
provided by this package or by the pinned official Desktop base.

`archive_store` borrows a serialized `Capy::Vault::Store`. The future adapter must
use an independent `tdata/capybara-archive` account registry, with the existing
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
empty namespace. No archive clear API bypasses registry retirement; clearing will
require a new generation in the future worker.

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

Pending: bounded capture worker, opt-in settings and UI, native edit/delete/expiry
hooks, original media admission before cache cleanup, account logout/passcode
integration and full-client testing. Secret-chat protocol support is a separate
required part of P2, not implied by this storage package.

`VerifiedInput` admits an already complete, unencrypted original inside an explicit
trusted local root, with its exact declared length. It rejects reparse ancestors,
hard links, directories, device/ADS/ambiguous paths, root-prefix siblings, oversized
and missing files. It holds a Win32 read handle that permits deletion but denies
new writes; the worker streams that handle instead of reopening a mutable path.
This is not a decryptor for Telegram's encrypted cache or a downloader of absent
originals. Native media selection and ownership gates remain pending.

API basis: [CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
and [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).
