# Native appearance

CapybaraGram uses warm neutral surfaces and amber accents. The dark direction follows the selected graphite concept; the light theme uses paper and sand colors. These are native Telegram themes, not a web overlay.

`prepare_appearance.py` applies only to the pinned upstream revisions, after the account, notes, brand and read-control patches. Every input and output is checked before any file is written. It does not access account data or change networking.

- Android: bundled **Capybara Light / Capybara Dark**, default for a fresh profile, introductory theme switch and direct note action in the chat header. Existing explicitly selected themes remain selected; the Capybara pair is available in appearance settings.
- Windows: replaces the default/day and bundled night palettes and default background; adds a dedicated notes/templates button to the chat header. Imported themes keep their own palette. The button uses the existing session/context guards and inserts templates only into a draft.

Native compilation, visual inspection and account-backed acceptance must be reported separately. A successful patch application is not a successful UI test. This is the first native implementation of the chosen direction, not a claim that every layout in the concept is implemented.

The `.attheme` and `.tdesktop-theme` resources adapt the pinned upstream theme palettes and retain their respective upstream GPL terms. The patch script is MIT. See the upstream licensing references in [BUILDING](../../docs/BUILDING.md).
