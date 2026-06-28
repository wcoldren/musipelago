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

### A2. Guess-the-song mode — "name the album / artist / song" — 🟡 · client/world · upstream?
You identify the playing track (fuzzy-match on `GenericTrack.{title,artist,album_title}` via
`difflib`). **We'll implement BOTH ways guessing ties into Archipelago checks:**

- **A2a — gate the existing check** — ✅ **DONE** (client-only, no regen, works on current seeds):
  "Guess mode" toggle in Settings; when on, finishing a track no longer auto-awards its check —
  a per-row **Guess** button opens a prompt and a correct (fuzzy) title guess awards the check via
  the shared `RootLayout.complete_track`. **Reveal = give up but STILL releases the check** (so an
  unguessable track can never soft-lock the seed/multiworld). Shipped on `feat/guess-mode` → `dev`.
- **A2c — Guess hints** (🟢🟡 · client): progressive hints to help guessing short of giving up —
  e.g. reveal the artist, then album, then word-count / first letters. Lets players make progress
  without a full reveal. Builds on the guess popup. (Distinct from AP's existing `!hint` server
  hints, which point to item locations.)
- **A2b — bonus "guess" checks** (🟡🔴, world + regen): generate a SECOND location per track
  ("Guess: <track>") so a correct guess is a genuinely *extra* check (more items/progression).
  Touches `Locations.py.j2` / `Items.py.j2` / `Rules.py.j2` and requires regenerating seeds.
  **AP constraint:** locations are fixed at generation, so bonus checks cannot be added purely
  client-side — they must exist in the seed. Do A2a first, then A2b.

Reveal is available today via a **per-row Reveal button** + the `...` menu (see A3). A reveal
**hotkey** is in the backlog (D5).

### A3. Hidden-metadata / "unknown song" mode — learn your library — 🟢🟡 · client — ✅ **DONE**
Client-side toggle in a new Settings panel (reached via the existing settings icon, persisted in
JsonStore). Masks track title/artist + the AP location line as "Unknown" in the list rows and
now-playing bar until a track is revealed; reveal happens on finish or via a right-click "Reveal"
peek. Album names stay visible. Real values kept as `raw_*` so playback is unaffected. Established
the **client Settings surface** that A2/C3 reuse. Shipped on `feat/client-hidden-mode` → `dev`.
(Follow-up: Subsonic now-playing masking parity.)

- **Synergy:** A2 + A3 together = a music-learning quiz (blind listen → guess → reveal). Strong combo.

### A4. (enabler) Generator-side curation for traps/quiz — 🟡 · gen
Optional gen-app UI to tag a subset of tracks as the "trap pool" or quiz set, emitted into the
catalog. Builds on the existing per-track selection / meta-album curation patterns. Do after A1.

### A5. Randomizer controls — #mixtapes, #tracks-as-checks, subset + shuffle, minutes/pack — 🟡 · gen · upstream? — ✅ **DONE**
Extends meta-albums (`build_meta_albums`, `musipelago_apworld_gen.py`) from a fixed shuffle into a
controllable randomizer, surfaced as `GeneratePopup` controls (sibling of A4). Knobs: (a) number of
mixtapes = pack `count` (**already existed** — `meta_mode='N packs'`); (b) number of tracks used as
checks = **sample a subset of size K from the pool before packing** (✅); (c) shuffle on/off (✅);
(d) **minutes-per-pack** mode — greedily fill each mixtape to ~N minutes via `GenericTrack.duration_ms`,
each track landing on whichever boundary keeps the pack closest to target (✅, added on user request).
Shipped on `feat/randomizer-controls` (off `feat/meta-albums`) → `dev`; 8 tests (53 total, headless).

- **Decided: gen-app controls (v1).** AP **locations are fixed at generation time**, so the check-count
  and chosen track subset bake into the `.apworld` — they belong in the gen app, not the player YAML.
  This obeys the "generator is a pure function of `apworld_data`" insight (no world/template/client
  changes); the subset+shuffle happens before `build_meta_albums`, which already partitions cleanly.
- **A5b (deferred, world+regen):** a YAML/AP-seed variant — bake the full catalog and subset+shuffle
  per-player at AP-generation using the AP seed (more Archipelago-native, per-player variation in a
  multiworld). Promote once online/multiworld play starts.

## B. UI / UX

### B1. Fix long-title text overflow — 🟢 · client · upstream? — ✅ **DONE**
The `CustomListItem` labels in `musipelagoclient.kv` lacked `shorten`, so long titles wrapped and
overflowed the fixed 100dp rows. Added `shorten: True; shorten_from: 'right'` to the four
`text_line_*` Labels (matching the now-playing widget) for single-line ellipsis. Shipped on
`fix/client-list-text-overflow` → `dev`.

### B2. Visual refresh + theming — 🟡 · gen ✅ **DONE** / client ⏳
~20 hardcoded RGBA values scattered with no central theme. Extract constants for a cohesive
palette/spacing, modernize cards (rounded corners via canvas), consistent fonts. Enables dark/light
variants with no code changes.

- **Gen app — ✅ done** on `feat/gen-ui-refresh` (off `dev`): new `theme.py` (DARK/LIGHT palettes +
  `RADIUS`/spacing) bound to App `col_*` `ColorProperty`s; `musipelagoapwgen.kv` re-themed (rounded
  `CustomListItem` cards, themed text/surfaces). Shipped alongside a **gen-UI clarity pass**: list
  pane headers + live "N albums · M tracks" count, empty-state hints, raw URI dropped from rows
  (now shows album duration), **visible "+ Add" / "✕ Remove"** buttons (the per-row `...` menu now
  only appears for artists' secondary action), a **real Settings popup** (live Dark/Light theme
  toggle persisted to the gen `JsonStore` + an About/how-to), and clearer `GeneratePopup` labels for
  the A5 mixtape controls. 10 headless tests (`test_gen_ui.py`).
- **Client — ⏳ not yet.** The same `theme.py` can drive `musipelagoclient.kv`; deferred.
- **Blank-pane regression fix** (`fix/gen-blank-panes`, off `dev`): the refresh wrapped each
  `RecycleView` in a `FloatLayout` for the empty-state overlay but gave them no `pos_hint`, so the
  lists were positioned at the window origin and panes looked blank (rows + buttons invisible, scan
  unreachable). Fixed with `size_hint: 1,1` + `pos_hint: {x:0,y:0}` on both RecycleViews. Also kept
  the Settings button out of the hidden search box (Local Files hid the whole bar incl. the recovery
  entry) by wrapping search inputs in `search_controls`, and added **last-folder memory**
  (`gen_settings.last_directory`, pre-filled at next login). Lesson: kv-*parse* tests don't catch
  *layout* bugs — these need a real-display smoke check.
- **Local-files onboarding fix** (`fix/local-files-onboarding`, off `dev`): the refresh had hidden
  the per-row `...` button that drove plugin action rows, leaving Local Files' "Create New Album" /
  "Scan Root Directory" rows dead (no buttons) → fixed by giving plugin rows a primary button routed
  to `on_item_menu_click`. Also **implemented Scan Root Directory** (each subfolder → a whole album,
  no per-track popups, via `add_to_apworld(curate=False)`), and added a **Settings → "Switch service
  / folder…"** recovery path (`App.restart_login`) so a wrong pick no longer needs a force-quit.
- **Output + handoff** (`feat/gen-output-and-yaml`, off `dev`): generated files now land in a
  **remembered output folder** (default `~/Musipelago`, changeable in Settings) instead of buried in
  `src/`; a **post-generation results dialog** shows the path + Open-folder + next-steps; a **starter
  YAML** is written next to the `.apworld`; and the mixtape `CheckBox`es became **ToggleButtons** (the
  bare checkboxes were invisible on the dark theme). The cross-app handoff is now a one-command
  helper: **`~/repos/AP/games/musipelago/gen.sh`** (in the AP workspace repo, not the fork) takes a
  built `.apworld` → playable AP seed (`Players: 1` verified), the first AP-workspace tooling for the fork.
- **Shareable seed helper + import polish** (`feat/import-multiselect-and-seed-tool`, off `dev`): the
  seed helper now **ships in the fork** as cross-platform **`tools/make_seed.py`** (stdlib only;
  locates Archipelago via `--ap-dir`/`$ARCHIPELAGO_DIR`/auto), so it's not tied to one machine; the AP
  `gen.sh` is now a thin wrapper around it. The results dialog gained a **Copy command** button (+ a
  remembered "Archipelago folder" Settings row). **Import album(s)** now multi-selects folders (one →
  named confirm, many → whole-album import). Readability: track-checklist `CheckBox`es → **`[x]/[ ]`
  ToggleButton rows**, the mixtape toggle glyph → ASCII, and right-pane row labels now **ellipsize**
  (`shorten`) instead of scrunching long titles.
- **Local scan correctness + art** (`fix/local-track-order-and-art` + `fix/track-order-by-filename`,
  off `dev`): `_scan_one_dir` now **orders tracks** via `sort_track_infos` — a folder-level heuristic
  that prefers **numbered filenames** (`01.`,`02.`…), else **unique tag track numbers**, else filename
  order. (First pass sorted purely by tag track number, but reissues restart/duplicate those per bonus
  set — e.g. Death "Leprosy (Deluxe Reissue)" had non-unique `n/36` tags while filenames `01.`–`36.`
  were authoritative — so filename-number wins.) Was raw `os.listdir` order, which mis-ordered tracks
  (bonus cuts interleaved) and made the victory track (`tracks[-1]`) wrong. `_build_album` also sets `display_image_url` from `find_cover_in_dir()` so
  **album covers show in the gen app** (stripped from the saved catalog; client re-derives art).
  Folder multiselect is an explicit **checklist** (Ctrl/Cmd-click was unreliable). Re-import existing
  albums to pick up the corrected order.

### B3. Album art display — 🟢 · client — ✅ **DONE (display ships upstream; masking added here)**
**Correction:** cover-art *display* was never missing — it already ships from the initial commit and
is present on `upstream/main`. The client has its own `AsyncImageWithHeaders` (`musipelago_client.py`,
not just the gen app), `CustomListItem.image_source` + `GenericPlaybackInfo.art_source` bound to it,
Subsonic signed `getCoverArt` URLs, and **local-files art** via external `cover.jpg`/`folder.jpg` +
embedded `mutagen` extraction (ID3 `APIC`, FLAC, MP4 `covr`, OGG Vorbis) in `local_files_backend.py`
(`_find_local_art`/`_extract_art_to_cache`). `KIVY_ICON` is only the *no-art fallback*, never a
permanent placeholder. The original entry was written on a misread of the gen-app widget.

The **real gap** (fork-specific) was that A3/A2a quiz modes leaked the answer through the cover art:
rows masked title/artist but not `image_source`; the local now-playing bar masked title/artist but not
`art_source`. **Fixed on `fix/hidden-art-leak`** — the cover is masked to `KIVY_ICON` when hidden &
not-finished and revealed through the existing finish/Reveal chokepoint (`unmask_row` in `utils_client`,
mirroring the title/artist masking). Closes the last metadata leak for blind-listen mode → completes
the **A2 + A3 quiz synergy**. (Subsonic *now-playing* masking — title + artist + art together — stays
in the separate "Subsonic now-playing masking parity" follow-up; row art already masks for both backends.)

- **Backlog extension ("other cool tokens"):** surface track count / album year in the row +
  now-playing metadata. `total_tracks` exists; **album year needs a new `GenericAlbum` field + backend
  changes** (heavier). Pairs with B2 theming. Not done.

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

### C5. Tests + CI — 🔴 · repo · upstream? — ✅ **DONE (foundation)** on `test/ci-foundation`
Pulled to the front (ahead of the roadmap's original "last" slot) because feature velocity had badly
outrun the safety net. A `tests/` suite now formalizes the verification harness written during the
feature sprint (which was otherwise stranded in a scratch dir): `build_meta_albums` partition/seed/
collision invariants, the per-track-selection queue/filter/dedup logic, an end-to-end Jinja render +
`py_compile` + name-uniqueness check, the guess-mode title matcher, and PluginManager discovery — 29
tests, headless. Added `.github/workflows/ci.yml` (py 3.11 + 3.12, xvfb + dummy SDL; no libvlc needed
— the guess matcher was extracted to `utils_client` so it tests without importing the VLC client).
Wired `[project.optional-dependencies] dev` + `[tool.pytest.ini_options]` in `pyproject.toml`.
(Follow-ups: client masking/now-playing tests once the client is refactored for headless import; CI
green confirmed on first push.)

## D. Backlog / smaller

- **D1.** "Edit tracks after adding" — ✅ **DONE** (`feat/gen-edit-tracks`, off `dev`): right-pane
  multi-track albums show an **Edit** button (Remove moved to the "…" menu) that reopens
  `TrackSelectionPopup` pre-checked to the current tracks. **Non-lossy** — `add_apworld_item` stamps a
  session-only `album._all_tracks`, so the editor lists every original track and you can re-add ones
  you removed. Shipped alongside: row de-cramping (smaller thumb/button), "Create New Album" →
  **"Import single album"**, and folder-memory polish (last service pre-selected; `last_directory`
  restore confirmed working).
- **D2.** Subsonic gaps: `get_playlist_with_tracks` stub + missing pagination. — 🟡 client
- **D3.** Settings UI + config module: window size, volume default, AP timeout, audio backend. — 🟡 client
- **D4.** Friendlier error messages (wrap low-level exceptions with context). — 🟢 all
- **D5.** Reveal hotkey — a meta-key reveals the currently-playing track. Needs new keyboard
  handling (`Window.bind(on_key_down=…)`); none exists in the client today. — 🟢🟡 client

---

## Execution order (features-first)

Agreed order — reliability is deferred because local play doesn't need auto-reconnect yet; it
jumps up the list once online/multiworld play starts. A2/A3 are client-side toggles (no regen).

0. **B1** — list-row text overflow — ✅ done.
1. **C4a** — quick cleanups & hygiene — ✅ done (dead code, `print()`→`Logger`, dropped `plyer`
   dep). The window-config dedupe and the broad-`except` pass (**C4b**) remain, deferred to step 9.
2. **A3** — hidden-metadata / "unknown song" mode — ✅ done (client toggle; built the Settings surface).
3. **A2** — guess-the-song mode (client toggle; builds on A3) — ✅ done (A2a).
4. **C5** — tests + CI — ✅ done (foundation) — **pulled forward** from "last": feature velocity had
   outrun the safety net, the harness was stranded in scratch, and it makes the upstream PRs reviewable.
5. **A1** — traps (flagship; first item needing world changes + the per-item dispatch hook).
6. **A4** — generator-side curation for traps/quiz (builds on A1).
7. **A5** — randomizer controls (#mixtapes / #checks / subset+shuffle / minutes-per-pack; gen-app, builds on meta-albums) — ✅ done.
8. **B3** — album art: display already shipped upstream; **hidden-mode art masking ✅ done**
   (`fix/hidden-art-leak`) → **B2** — visual refresh + theming (**gen app ✅ done** incl. a UI
   clarity pass + real Settings panel; client theming still pending).
9. **C3** — audio backend fallback factory (selector lives in A3's Settings surface).
10. **C1 + C2 + C4b** — reliability phase: auto-reconnect, thread-safety, broad-`except` hardening.
    Promote this the moment online/multiworld play begins.

**Backlog (opportunistic):** D1–D5 above; D3 is partly delivered by A3's Settings surface.
**Dependencies:** A3 → A2 (reveal plumbing) and A3 → Settings surface (reused by C3, B2);
A1 → A4; A5 builds on meta-albums; B3 pairs with B2; C4b travels with C1/C2.

## Key code references (for implementers)

- **Gameplay:** `apworld_template/{Items,Options,Types,Rules,__init__}.py.j2`;
  `musipelago_client.py` `_sync_owned_items` (~865) / `check_victory` (~934) / list population (~654);
  `backends.py` (`GenericTrack`, `AbstractClientHost`).
- **UI:** `musipelagoclient.kv` (`CustomListItem` ~235–289, `GenericPlaybackInfo` ~127–189);
  `client_ui_components.py`.
- **Robustness:** `musipelago_client.py` `run()` (~841); `vlc_/ff_/kivy_audio_player.py`; `pyproject.toml`.
