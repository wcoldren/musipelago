# Musipelago — Roadmap

Planned features and improvements for this fork. Grounded in a code review of the client,
generator, apworld templates, and backends.

Status legend — **effort**: 🟢 quick (hours) · 🟡 medium (1–3 days) · 🔴 large (week+).
**surface**: `gen` (generator app) · `world` (apworld templates) · `client` · `data` (JSON/options).
**upstream?**: clean general feature worth a PR to `tepiloxtl/musipelago` vs. fork-personal.

Workflow: each item lands on its own `feat/…`/`fix/…` branch off `main`, merged into `dev`.

---

## A. Gameplay mechanics (the fun stuff)

### A1. Traps — "listen to N trap songs before continuing" — 🟡 · world+client · upstream?
Trap items are already scaffolded but disabled: `apworld_template/Items.py.j2` has commented
`"Forcefem Trap"/"Speed Change Trap"` under `junk_items`, and `ItemClassification.trap` is
supported. The blocker is that the **client has no per-item dispatch** — `_sync_owned_items`
(`musipelago_client.py:865`) only special-cases `"Album finished!"`.

- **world/data:** uncomment/define trap items + weights; add options `EnableTraps` (Toggle) and
  `TrapSongCount` (Range) in `Options.py.j2`, thread through `MusipelagoOptions` and
  `fill_slot_data` (`__init__.py.j2:113`); include an item→classification map in `slot_data`.
- **client:** add a dispatch hook in `_sync_owned_items` (~`:893`) → new
  `AbstractClientHost.on_trap_received(name, meta)` (`backends.py`); the local-files/subsonic
  client implements a modal that locks input and force-plays N tracks before resuming.
- **design choice:** trap songs = random from the library at trigger time (simplest) **or** a
  curated "trap pool" chosen at generate time (see A4). Recommend starting random, add curation later.

### A2. Guess-the-song mode — "name the album / artist / song" — 🟡 · client (client-side toggle) · upstream?
All metadata is already client-side (`GenericTrack.{title,artist,album_title}`), so this is
client UI + a **client-side toggle** (a setting, not a per-seed option — flip it anytime, works on
existing seeds).

- On track finish (`on_playback_finished` → `send_location_check`), gate the check behind a prompt:
  type artist/title/album, fuzzy-match (`difflib`) against known metadata; correct → the check
  fires; skip → reveal but maybe no credit (configurable).
- Hooks: the finish→check path in the backend client hosts; the row/now-playing render.
- **design choice:** strict gate (must guess to get the check) vs. optional self-quiz overlay.

### A3. Hidden-metadata / "unknown song" mode — learn your library — 🟢🟡 · client (client-side toggle)
Pure display mask + a **client-side toggle** (a setting, not a per-seed option). Mask `text_line_*`
and now-playing title/artist with "???" until the track is finished (or guessed in A2). Data stays
intact; only rendering changes in the RecycleView population (`musipelago_client.py:654–690`) and
`GenericPlaybackInfo`. Establishes a small **client Settings surface** (`get_settings_ui` returns
None today) that A2 and the audio selector (C3) reuse.

- **Synergy:** A2 + A3 together = a music-learning quiz (blind listen → guess → reveal). Strong combo.

### A4. (enabler) Generator-side curation for traps/quiz — 🟡 · gen
Optional gen-app UI to tag a subset of tracks as the "trap pool" or quiz set, emitted into the
catalog. Builds on the existing per-track selection / meta-album curation patterns. Do after A1.

## B. UI / UX

### B1. Fix long-title text overflow — 🟢 · client · upstream? — ✅ **DONE**
The `CustomListItem` labels in `musipelagoclient.kv` lacked `shorten`, so long titles wrapped and
overflowed the fixed 100dp rows. Added `shorten: True; shorten_from: 'right'` to the four
`text_line_*` Labels (matching the now-playing widget) for single-line ellipsis. Shipped on
`fix/client-list-text-overflow` → `dev`.

### B2. Visual refresh + theming — 🟡 · client · upstream?
~20 hardcoded RGBA values scattered through `musipelagoclient.kv` with no central theme. Extract a
`theme.kv` (or constants) for a cohesive palette/spacing, modernize cards (rounded corners via
canvas), consistent fonts. Enables future dark/light variants with no code changes.

## C. Foundation / robustness (make play reliable)

### C1. AP auto-reconnect — 🔴 · client · upstream? — **high value for real play**
`ArchipelagoClient.run()` is one-shot: a server restart or network blip ends the session with no
retry (the `async for message` loop just exits). Wrap connect+loop in an exponential-backoff
reconnect with state resync. This is the most impactful reliability fix.

### C2. Thread-safety pass — 🟡 · client
The async websocket thread mutates shared state (`owned_item_ids/names`, `received_*`,
`victory_reported`) read by the UI thread, with no locks. Marshal all state changes through
`Clock.schedule_once` (already used in places) or add a lock; also harden the documented
ReceivedItems↔DataPackage race that `_sync_owned_items` works around.

### C3. Audio backend fallback factory — 🟡 · client · upstream?
Three players exist (`vlc_/ff_/kivy_audio_player.py`) but only VLC is used — VLC-or-bust (the
"Bundled engine missing" path at launch). Add a factory that tries VLC → ffpyplayer → Kivy, plus a
settings selector. Removes the hard VLC dependency.

### C4. Cleanups & hygiene — 🟢 · all · upstream?
Delete dead code (abandoned plyer block `local_files_backend.py:347–381`, commented victory block
`musipelago_client.py:908–932`); replace stray `print()` protocol logging (`:992,1004,1127…`,
`vlc_audio_player.py:20`) with `Logger`; tighten `except Exception: pass` swallowers (50+ spots)
to scoped exceptions + logging; drop the now-unused `plyer` dep from `pyproject.toml`; dedupe the
duplicated window-config code between client and gen apps.

### C5. Tests + CI — 🔴 · repo · upstream?
No test suite today. Seed one from the verification harness written during the macOS-fix work
(`build_meta_albums`, template rendering, JSON parse, plugin discovery) and add GitHub Actions.
Locks in the curation features + the macOS picker/ws fixes against regressions.

## D. Backlog / smaller

- **D1.** "Edit tracks after adding" (deferred v2 of per-track selection): an "Edit tracks" action
  next to "Remove" on APWorld-list items, re-opening `TrackSelectionPopup` against a committed album. — 🟡 gen
- **D2.** Subsonic gaps: `get_playlist_with_tracks` stub + missing pagination. — 🟡 client
- **D3.** Settings UI + config module: window size, volume default, AP timeout, audio backend. — 🟡 client
- **D4.** Friendlier error messages (wrap low-level exceptions with context). — 🟢 all

---

## Execution order (features-first)

Agreed order — reliability is deferred because local play doesn't need auto-reconnect yet; it
jumps up the list once online/multiworld play starts. A2/A3 are client-side toggles (no regen).

0. **B1** — list-row text overflow — ✅ done.
1. **C4a** — quick cleanups & hygiene (dead code, stray `print()`→`Logger`, drop `plyer` dep,
   dedupe window-config). The bigger broad-`except` pass is **C4b**, deferred to step 8.
2. **A3** — hidden-metadata / "unknown song" mode (client toggle; seeds the Settings surface).
3. **A2** — guess-the-song mode (client toggle; builds on A3).
4. **A1** — traps (flagship; first item needing world changes + the per-item dispatch hook).
5. **A4** — generator-side curation for traps/quiz (builds on A1).
6. **B2** — visual refresh + theming.
7. **C3** — audio backend fallback factory (selector lives in A3's Settings surface).
8. **C1 + C2 + C4b** — reliability phase: auto-reconnect, thread-safety, broad-`except` hardening.
   Promote this the moment online/multiworld play begins.
9. **C5** — tests + CI (seed from the existing verification harness).

**Backlog (opportunistic):** D1–D4 above; D3 is partly delivered by A3's Settings surface.
**Dependencies:** A3 → A2 (reveal plumbing) and A3 → Settings surface (reused by C3, B2);
A1 → A4; C4b travels with C1/C2.

## Key code references (for implementers)

- **Gameplay:** `apworld_template/{Items,Options,Types,Rules,__init__}.py.j2`;
  `musipelago_client.py` `_sync_owned_items` (~865) / `check_victory` (~934) / list population (~654);
  `backends.py` (`GenericTrack`, `AbstractClientHost`).
- **UI:** `musipelagoclient.kv` (`CustomListItem` ~235–289, `GenericPlaybackInfo` ~127–189);
  `client_ui_components.py`.
- **Robustness:** `musipelago_client.py` `run()` (~841); `vlc_/ff_/kivy_audio_player.py`; `pyproject.toml`.
