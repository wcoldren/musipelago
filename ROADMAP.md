# Musipelago — Roadmap

Planned features and improvements for this fork. Grounded in a code review of the client,
generator, apworld templates, and backends.

Status legend — **effort**: 🟢 quick (hours) · 🟡 medium (1–3 days) · 🔴 large (week+).
**surface**: `gen` (generator app) · `world` (apworld templates) · `client` · `data` (JSON/options).
**upstream?**: clean general feature worth a PR to `tepiloxtl/musipelago` vs. fork-personal.

Workflow: each item lands on its own `feat/…`/`fix/…` branch off `main`, merged into `dev`.

---

## A. Gameplay mechanics (the fun stuff)

### A1. Traps — receive a trap item, suffer an effect — 🟡 · world+client · upstream?

**A1-dispatch — once-only dispatch infrastructure — ✅ DONE** on `feat/traps-dispatch` (off `dev`).
The scaffolding was far thinner than "uncomment two items"; the review found:
- `create_junk_items` only pooled `ItemClassification.filler`, so trap items were **silently
  excluded** even when uncommented (the comment lied). The stub `"Forcefem Trap"` (edgy, dropped)
  and `"Speed Change Trap"` were commented out; there were **no options, no slot_data, and no
  client dispatch** (`_sync_owned_items` only handled album unlocks + the victory item).
- **The hard part is once-only firing, not the effect.** Album unlocks are persistent
  set-membership (safe to reprocess the whole backlog); a trap is a one-shot event that must fire
  **exactly once per received instance** and never re-fire on reconnect (server replays from
  index 0) or app restart (`received_items` rebuilt from scratch).

What shipped (content-free reference effect — a dismissable "🎵 You hit a trap!" modal):
- **world:** `EnableTraps` (Toggle, default off) + `TrapPercentage` (Range 0–100, default 20) in
  `Options.py.j2`; a `trap_items`/`trap_weights` pair + one reference trap `"Bad Track Trap"`
  (`ItemClassification.trap`) in `Items.py.j2`; `create_junk_items` rewritten as the AP
  **trap-fill split** (carve `round(N·pct/100)` of the filler budget into weighted trap picks);
  `fill_slot_data` emits `"traps": {"enabled", "names"}` (`__init__.py.j2`). `Seed`/`Slot` were
  already in slot_data — reused as the persistence key.
- **client:** pure `count_pending_traps(received_items, id_to_item_name, trap_names, already_fired)`
  in `utils_client.py` (headless-tested); `ArchipelagoClient._load_trap_state` (Connected) +
  `_dispatch_pending_traps` (hung off `_sync_owned_items`) — mirrors `check_victory`'s count-by-id
  idempotency but **persists a `_traps_fired` cursor per `trap_cursor::Seed::Slot`** in the
  JsonStore, so reconnect/restart fire 0 already-handled traps. `MusipelagoClientApp.trigger_trap`
  shows the modal **serialized one-at-a-time** (queue; mirrors the gen `TrackSelectionPopup`
  pattern) and calls the new `AbstractClientHost.on_trap_received(name)` extension hook
  (`backends.py`, default no-op). 10 headless tests (`test_traps.py` + `test_e2e_render.py`).

**Next — concrete trap effects (register into `trigger_trap`/`on_trap_received`; deferred):**
The dispatch table is the plumbing; effects are cheap to add. Content-need tiers:
- **Tier 0 (no audio shipped — manipulate the player's own library/playback/UI):**
  - **Shuffle Trap** — endure N random tracks from *your own* library before resuming (the
    licensing-clean "rickroll": your music, not your choice). Natural flagship.
  - **Speed Change Trap** — next track chipmunk-fast / sludge-slow (needs a new `set_rate` wrapper
    across the vlc/ff/kivy players — none exposes rate today).
  - **Re-mask Trap** — re-hide the next track's title/artist/art (pure reuse of A3 masking).
  - **Repeat Trap** — next track must loop K times before its check releases.
  - **Guess-gate Trap** — force one track behind a guess prompt (pure reuse of A2a).
  - **Soft Re-lock Trap** — re-lock a random unlocked album for T minutes, **auto-expiring**.
  - **Cosmetic Trap** — garish theme flip (reuse B2) / scrambled rows / shake. Harmless, funny.
- **Tier 1 (player-supplied, opt-in):** a Settings path for *your own* trap clip (BYO rickroll).
- **Tier 2 (bundled):** a tiny CC0/public-domain stinger, only if wanted.

**Trap-safety + softlock rules (govern every effect — non-negotiable):**
1. **No softlock** — a trap must auto-resolve and can NEVER permanently block an AP location
   (time-boxed or always-finishable; soft re-locks must auto-expire).
2. **No hearing/equipment hazard** — **NO sudden loud-volume traps** (a "Volume Trap" was
   considered and **dropped**: forced loudness can hurt ears/gear). No abrupt volume jumps; any
   audio effect stays within the user's current level.
3. **No flashing/seizure-risk visuals** in cosmetic traps.

- **A4 synergy:** a curated "trap pool" chosen at generate time (see A4) can later feed Shuffle.

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

### A6. Random / shuffled album reveal order (incl. the starting album) — 🟢 · world/data (+gen) · upstream?
"Always Eaten Back to Life first" is the **fixed `StartingAlbum: album_001`** (`Options.py.j2`
`StartingAlbum(Choice)`, `default = 1` = first album in catalog order). Albums are independently
item-gated (no chain), so *subsequent* unlock order already varies per seed via AP's fill — only
the start is pinned.
- **Works today, no code:** set **`StartingAlbum: random`** in the player YAML. AP `Choice`
  options accept `random` (and `random-low`/`random-high`/weighted dicts), so AP rolls a random
  album as the start. That alone removes the fixed first album.
- **Roadmap extras:** (a) make random the convenient default — emit `StartingAlbum: random` in the
  gen app's starter YAML and document it; (b) optional true **reveal-order control** — a gen/world
  knob to bias unlock placement so albums reveal in a deliberately shuffled cadence. Mostly docs +
  a starter-YAML default since the core already works.

### A7. Per-song unlock granularity (unlock single tracks, not whole albums) — 🔴 · world+regen · upstream?
Today unlocking is **per album**: each album is one Region (`Regions.py.j2:22`
`create_region_and_connect`) whose entrance "Unlock [artist] [album]" is gated by a single album
progression item (`Rules.py.j2:23-24`, `state.has("[artist] [album]")`); every track is a location
inside that region, so one item reveals the whole album (`ap_skeleton_chapters` = one progression
item per album). **No per-track gating exists.** A "single song" mode gates each track on its own
item/rule (per-track entrance rules or per-track regions) + one unlock item per track — a
structural generation-time change across `Items/Locations/Regions/Rules.py.j2` (+ `Types`/`__init__`)
that **requires regen** (AP locations/items are fixed at gen). Knock-ons: item count grows to
~#tracks (re-balance the filler/trap/overshoot math); victory + `StartingAlbum` semantics shift
(start = a track? an album?); pairs with A2b. Best as a gen/world **mode toggle**
(per-album default ↔ per-track) so existing seeds are unaffected. (`AllowPlayingAnyTrack` already
lets you *play* any track regardless of unlock — this is about *check-gating*.)

### A8. Helpful / "boon" items + filler review — 🟡 · world (+client) · upstream?
**Current pool (review, as of `feat/traps-dispatch`):** three classes only — **progression**
("Album finished!" victory + one per-album unlock in `ap_skeleton_chapters`), **filler** (4
pure-flavor no-ops — "Scratched disc", ".mov file", "Funny animal .gif", "Concert tickets" in
`junk_items`, equal `junk_weights`, **zero gameplay effect**), and **trap** ("Bad Track Trap").
There are **no `ItemClassification.useful` items and no positive-effect items** — filler is cosmetic
text, traps are the only items that *do* something.
**Proposal — add helpful "boon" items as the positive counterpart to traps**, reusing A1's
once-only dispatch (the `_dispatch_pending_traps` / `on_trap_received` machinery generalizes to a
per-item effect hook). Candidates (client-side, softlock-safe): **Reveal token** (reveal one hidden
track — A3 synergy), **Skip/auto-complete token** (release one track's check — also a guess-mode
escape, A2), **Hint** (cheap progressive hint, A2c), **Unlock-a-track / free unlock** (grant one
album/track early — pairs with A7), **cosmetic/theme boon**. Classify `useful` (or `progression`
if they grant unlocks). Also rebalance `junk_weights`, decide the junk/trap/useful split, and fold
in the known item-pool **overshoot** quirk (`get_total_locations - len(itempool) - 1` ignores the
locked victory locations). Same trap-safety rules apply (no softlock).

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
  (bonus cuts interleaved) and made the victory track (`tracks[-1]`) wrong.
- **Locked-album art + quiet generation** (`feat/locked-art-and-quiet-gen`, off `dev`): client album
  rows now show a **"?" placeholder (`LOCKED_ICON`) until the album is unlocked** (`web_source` gated on
  `is_owned`; reveals the real cover when the unlock item arrives — already-dimmed rows get the art
  cue too). Removed the leftover debug `print()`s in `apworld_template/Items.py.j2` that spammed
  `[Artist] [Album]` banners during generation. (Album unlock is independent/item-gated per album — no
  linear chain.)
- **App icon** (`feat/app-icon`, off `dev`): both apps' window icon set to the user's Musipelago logo
  (`resources/musipelago_icon.png`). The source PNG had a baked-in transparency checkerboard (fully
  opaque) — keyed out the two neutral checker greys, cropped to content, squared to 512. Art-less
  filler stays the neutral music-note. `_build_album` also sets `display_image_url` from `find_cover_in_dir()` so
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

### B4. Message log / chat console (TextClient-style) — 🟡 · client · upstream?
Other AP clients (TextClient, BizHawk) show a scrolling feed of items sent/received, hints, and
chat; the music client shows none of it — you can only watch the stream on the MultiServer console.
The plumbing is half-built: inbound `PrintJSON` is parsed and item/location/player ids resolved to
names (`musipelago_client.py` ~1494 via `get_ap_info`), but only the **latest** line is kept — it
overwrites the single-line `ap_status_text` bar (`StringProperty` :597, rendered by the lone
`ap_status_bar` Label, `musipelagoclient.kv:117`). Outbound chat already works:
`send_chat_message`/`_async_send_say` send a `Say` packet (:1634), used today only to fire `!hint`.
Build: a collapsible **log panel** (a `RecycleView` like the track lists, or a scrolling Label in a
`ScrollView`) that **appends** each resolved `PrintJSON` line to a ring buffer (colour by part type),
plus an optional **chat `TextInput`** wired straight to `send_chat_message`. Pure UI over existing
parsing + send paths; no protocol changes. Clean and general → worth a PR upstream.

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

- **C4-lint — lint/format foundation — ✅ DONE** on `chore/lint-and-format` (off `dev`): adopted
  **ruff** (lint + format) configured in `pyproject.toml` (`select=[E,F,W,I,UP,B,SIM]`, line-length
  100), a repo-wide `ruff format` reflow, a **`.pre-commit-config.yaml`** (ruff + whitespace hooks,
  scoped away from the Jinja `apworld_template/` payload and vendored licenses), a **CI `lint` job**
  in `ci.yml`, and **pinned the floating runtime deps**. Ruff caught **real bugs**, all fixed here:
  5× `F821` deferred-lambda `except … as e` that would `NameError` on the error path
  (`local_files_backend.py`, `subsonic_backend.py` — capture the message before the `Clock` lambda);
  a silently-shadowed duplicate `get_settings_ui` in `subsonic_backend.py`; 2 dead locals; 2 unused
  imports; and **10 bare `except:` → `except Exception:`**. 94 tests stay green. The stray-`print()`
  swap was already done in C4a; the remaining `utils_client.py` prints are the intentional
  last-resort excepthook fallback.
- **C4b (remaining):** the broad-`except` swallowers (tracked via ruff `BLE001` —
  `ruff check --select BLE001 --statistics`) and a deferred style burn-down (the `ignore` list in
  `[tool.ruff.lint]`: `B007/B027/B905/SIM102/SIM105/SIM118/E731/E741`); the window-config dedupe.
  Travels with the C1/C2 reliability phase.

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
- **D6.** App-icon polish — the current `resources/musipelago_icon.png` is a placeholder (a detailed
  AI raster with text, keyed off a baked checkerboard → mushy/haloed at icon sizes). Replace with a
  **simple, bold, flat mark** (single symbol, *no text*, limited palette, generous padding) exported
  with **true alpha** (generate on a solid bg + remove.bg/Inkscape rather than relying on AI
  "transparency"). Add **multi-resolution `.icns` (macOS `iconutil`) + `.ico` (Windows)** for
  packaging. (AP's icon is crisp because it's a simple flat logo at exact sizes.) — 🟢 all

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
   **Dispatch + once-only infra ✅ done** (`feat/traps-dispatch`); concrete effects (Shuffle/
   Speed/Re-mask/…) register into it next — see A1.
6. **A4** — generator-side curation for traps/quiz (builds on A1).
7. **A5** — randomizer controls (#mixtapes / #checks / subset+shuffle / minutes-per-pack; gen-app, builds on meta-albums) — ✅ done.
8. **B3** — album art: display already shipped upstream; **hidden-mode art masking ✅ done**
   (`fix/hidden-art-leak`) → **B2** — visual refresh + theming (**gen app ✅ done** incl. a UI
   clarity pass + real Settings panel; client theming still pending).
9. **C3** — audio backend fallback factory (selector lives in A3's Settings surface).
10. **C1 + C2 + C4b** — reliability phase: auto-reconnect, thread-safety, broad-`except` hardening.
    Promote this the moment online/multiworld play begins.

**Backlog (opportunistic):** D1–D5 above; D3 is partly delivered by A3's Settings surface. Newer
captures: **A6** (random album reveal — `StartingAlbum: random` usable now, small) and **A8**
(helpful/"boon" items + filler review) are gameplay siblings of A5/A1; **A7** (per-song unlock) is a
larger world+regen item; **B4** (message log / chat console) is a UI backlog item.
**Dependencies:** A3 → A2 (reveal plumbing) and A3 → Settings surface (reused by C3, B2);
A1 → A4; A1 → A8 (boon items reuse the trap dispatch hook); A5 builds on meta-albums; B3 pairs
with B2; A7 pairs with A2b and ↔ A6 (start semantics); C4b travels with C1/C2.

## Key code references (for implementers)

- **Gameplay:** `apworld_template/{Items,Options,Types,Rules,__init__}.py.j2`;
  `musipelago_client.py` `_sync_owned_items` (~865) / `check_victory` (~934) / list population (~654);
  `backends.py` (`GenericTrack`, `AbstractClientHost`).
- **UI:** `musipelagoclient.kv` (`CustomListItem` ~235–289, `GenericPlaybackInfo` ~127–189);
  `client_ui_components.py`. Message log/chat (B4): `ap_status_text` (`musipelago_client.py:597`),
  `PrintJSON` handler (~1494), `ap_status_bar` (`musipelagoclient.kv:117`), `send_chat_message` (:1634).
- **Robustness:** `musipelago_client.py` `run()` (~841); `vlc_/ff_/kivy_audio_player.py`; `pyproject.toml`.
