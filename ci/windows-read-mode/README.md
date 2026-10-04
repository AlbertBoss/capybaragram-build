# Windows silent reading

Native integration against `telegramdesktop/tdesktop@80158983dba09d3bf5d96701f21473d6c34bf5f5`.
Applied after appearance, guarded by exact composed input/output hashes.

- One policy per `MTP::Instance`; default off. Stored in the account's encrypted
  Telegram session settings, with an optional versioned suffix. Logout clears
  in-memory permissions; unrelated account slots keep their own mode.
- The native chat menu and Capy tools menu expose the mode and explicit reading.
  Manual reading is scoped to one peer/topic and the loaded maximum message id
  captured when the dialog opens. Saved sublists do not inherit a whole-history
  manual read action.
- Ten TL methods are gated at the shared application request boundary: chat and
  channel history, discussion, saved history, message contents, mentions,
  reactions, poll votes and stories. Login, normal sending and downloads proceed.
- Suppression happens before any DC/socket enqueue. The queued terminal local
  error lets `Sender` register its request first; normal cancellation removes
  callbacks. No successful server response or `pts` update is fabricated; blocked
  work is never flushed when the user disables the mode.
- Explicit permission is bound to an allocated request id and TL constructor,
  consumed once, and cleared by mode/session changes. Returned server responses
  are parsed and account/layer lifetimes checked before displaying success.

The policy test checks ten-account isolation and permission misuse. Source tests
do not establish Telegram behavior. A native client build and a real two-account
test remain required. Windows secret chats are a separate, unimplemented feature.
Online status and typing are not part of this mode.

Full client run 37160170114 failed at the new menu translation unit: missing style_layers declarations and the three-argument menu callback. Both observed source errors were corrected; the pinned preparation and double-apply checks pass. Run 37171270131 passed read-mode preparation but stopped before compilation because Windows CRLF checkout differed from the voice payload pins. The exact error was reproduced locally and fixed by normalizing only CRLF-to-LF while preserving content pins. Run 37171862699 compiles both repairs together with the offline voice UI/worker. There is no successful Windows executable with this feature yet; live peer acceptance remains pending.
