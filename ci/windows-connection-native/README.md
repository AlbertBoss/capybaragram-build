# Native Windows connection integration

Experimental opt-in route for Telegram MTProto, using the reviewed MIT tglock
core and the bounded C++ controller. No hosted Worker, extra browser, external
proxy subscription, account credentials or system-wide routing is used by this
module. The library listens only on `127.0.0.1` with an ephemeral in-memory secret.

The client applies the runtime proxy only to `MTP::Session::refreshOptions`.
Saved proxy settings, proxy lists, account authorization and tdata serialization
are unchanged. Disabling restores the user's normal proxy selection immediately;
choosing a normal proxy revokes a pending startup. Normal proxy rotation is
suspended while the runtime override is active. Native account proxy-change
subscriptions reconnect existing sessions without deleting their auth keys.

The control is available from a chat's CapybaraGram menu and the phone/QR login
screen, applies to all accounts, and resets when the application exits. The login
button sits below Settings and follows the native cover, transition, language
and hide/show lifecycle. Its dialog closes if its login widget is destroyed.
The chat dialog retains its session-change and passcode-lock guards; actions in
either dialog reject a destroyed owner, application shutdown or a passcode lock.
Calls, HTTP downloads and other apps retain their
normal routing. Local startup is not evidence of a successful Telegram connection.

`prepare_windows_connection.py` pins all eight composed native hosts and seven
installed files, validates everything before writing, and rejects a different
upstream revision, double application, payload collision or symlink escape.
It follows archive preparation and runs only in the Windows Candidate profile.

The pinned desktop CMake helper sets a static MSVC CRT. Therefore
`build_windows_library.py` requires MSVC 14.44, SDK 10.0.26100.0, Rust 1.88.0,
an explicit x64 target and `+crt-static`. Its manual compatibility workflow links
the actual C ABI and controller probes with `/MT`, rejects linker warnings and
checks executable imports for dynamic CRT DLLs. Debug client integration is
rejected until a matching Rust Debug CRT build is separately verified.

Already verified: core runtime (113 tests and 632 C++ ABI assertions on each of
Windows/Linux, run 37184002484) and controller runtime (13 assertions including
2,000 rapid requests on each, run 37185110803). Two upstream external Telegram
tests were explicitly skipped. Neither result proves live Telegram connectivity.
Production static CRT compatibility passed in run 37187970195. The whole native
client, the new pre-login UI, VPN transitions and real account/session acceptance
remain separate checks. A source transformation passing is not a compiled UI.

Sources: [pinned desktop CRT policy](https://github.com/desktop-app/cmake_helpers/blob/428f37a41f936922cd3bb0159a357cca22ad359c/variables.cmake),
[Rust CRT and foreign linkage](https://doc.rust-lang.org/reference/linkage.html),
[pinned tglock](https://github.com/by-sonic/tglock/tree/8617d25f3ae9bddb158a6703d1d02e453ebd39ba).
