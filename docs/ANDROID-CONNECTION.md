# Native Android connection integration

This is development code. A successful isolated JNI test is not proof that the
Telegram client, an actual provider or a VPN transition works. The first full
Android candidate containing this integration has not yet passed its build.

The pinned Android source is
[`62b56a07`](https://github.com/DrKLO/Telegram/tree/62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c).
`prepare_android_connection.py` applies after notes, read controls, appearance,
archive and voice. It verifies five exact host inputs and seven payloads before
writing any changes. Reapplication, drift and overwriting added sources are refused.
An explicit R8 keep rule preserves the JNI bridge class and native method names.

The native chat menu has a **CapybaraGram · Connection** item. The login screen
has a labelled **Connection** button, so the route can be enabled before account
authentication. Both open the same native control dialog; it also links to the
ordinary Telegram proxy settings. Lifecycle hooks close the dialog on pause,
fragment destruction, owner change and app lock. Account keys never enter the
transport bridge, and these transformations do not change authentication.

`ConnectionController` keeps one worker, one replaceable command and one coalesced
UI delivery. Native start/stop runs off the UI thread. `MemoryRoute` serializes
native proxy application, retains the local token as wipeable bytes and updates
only initialized account slots. New account initialization applies the current
route before and after `native_init`, covering a manual switch during initialization.
The unavoidable Java JNI String is temporary; it cannot be securely wiped and is
not retained or logged by the coordinator.

Manual proxy selection immediately advances the route generation, wipes the
override and restores the selected settings. Worker cancellation is posted outside
the route lock and coalesced on the UI thread. Its generation check prevents a
delayed cancellation from stopping a newer user activation. Controller commands
must never run while the route lock is held. Dialog actions reject a changed
generation. No override token is written to SharedPreferences or `SharedConfig`.

The mode is opt-in, global to this app process and resets on process restart.
`LOCAL_READY` means only that the local listener is running. The dialog explicitly
directs the user to Telegram's own connection indicator for service reachability.
The transport is not a VPN or an anonymity claim. Actual mobile providers,
authentication, messaging, media and VPN on/off transitions remain acceptance gates.

Local Java compilation and synthetic native targets currently prove 27 controller
assertions (including 2,000 coalesced commands), 24 route assertions and ten guarded
preparation checks. They do not execute the Android UI or Telegram connection.
Actual frozen ARM64+x86_64 JNI compilation and API 30 JNI execution are separately
recorded in the package README and source provenance.

`build_android_library.py` builds only the pinned frozen ARM64 transport for the
candidate and installs the JNI with checksummed normal/build dependency notices.
It does not repeat unchanged isolated native test suites. The candidate collector
requires this JNI and the exact notice asset. Package metadata and notice contents
are checked against the registry lock and the original checksummed `.crate` archive.

The transport includes Apache-2.0 code. Telegram's Android source uses GPLv2 or
later, so the intended combined distribution path is GPLv3, subject to review of
the full app dependency inventory and delivery of corresponding source and license
texts. The MIT build-control repository does not relicense the entire app.
The [Apache Software Foundation's compatibility explanation](https://www.apache.org/licenses/GPL-compatibility)
and [GNU's GPLv3 guide](https://www.gnu.org/licenses/quick-guide-gplv3.html)
support this compatibility distinction. Public release remains gated on the complete
license/source package; these references do not constitute final legal review.
