import difflib
import os
import re
import sys
import traceback

from unidecode import unidecode


def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Catches and logs *all* unhandled exceptions without quitting."""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        from kivy.logger import Logger

        Logger.critical(f"--- UNHANDLED GLOBAL EXCEPTION ---:\n{error_msg}")
    except ImportError:
        print(f"[CRITICAL] --- UNHANDLED GLOBAL EXCEPTION ---:\n{error_msg}", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"--- UNHANDLED GLOBAL EXCEPTION (RAW) ---:\n{error_msg}", file=sys.stderr)
    print("=" * 80, file=sys.stderr)


# Set the hook
sys.excepthook = global_exception_handler

# --- Config & Env ---
# This is no longer needed here, plugins load their own
# dotenv.load_dotenv()
# CLIENT_ID = ...


# --- Helpers ---
def resource_path(relative_path):
    """Get absolute path to resource, works for dev, pipx, and PyInstaller"""

    # 1. PyInstaller --onefile
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)

    # 2. PyInstaller --onedir
    if getattr(sys, "frozen", False):
        base_path = os.path.dirname(sys.executable)
        # Check for PyInstaller 6+ _internal folder
        internal_path = os.path.join(base_path, "_internal")
        if os.path.exists(internal_path):
            return os.path.join(internal_path, relative_path)
        return os.path.join(base_path, relative_path)

    # 3. Development / Pip / Pipx
    # Anchors to the location of THIS file (utils.py)
    base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


# Default album-art placeholder (NOT the Kivy logo anymore — a neutral music-note image).
# Kept under the name KIVY_ICON so the many art-fallback call sites need no change.
KIVY_ICON = resource_path(os.path.join("resources", "album_placeholder.png"))


def filter_to_ascii(text):
    return unidecode(str(text))


# --- Guess-mode title matching (pure; used by the client's guess feature) ---
def _normalize_title(s):
    """Lowercase, drop parenthetical/bracket tags (e.g. '(Remastered 2012)'), strip punctuation,
    and collapse whitespace — so guesses match titles loosely."""
    s = (s or "").lower()
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", s)  # remove (…)/[…]/{…} annotations
    s = re.sub(r"[^a-z0-9]+", " ", s)  # punctuation -> space
    return " ".join(s.split()).strip()


def _titles_match(guess, answer):
    """True if a guessed title matches the real title (normalized equality or fuzzy ratio)."""
    g, a = _normalize_title(guess), _normalize_title(answer)
    if not g or not a:
        return False
    if g == a:
        return True
    return difflib.SequenceMatcher(None, g, a).ratio() >= 0.85


# --- Trap dispatch (pure; used by the client's once-only trap firing) ---
def count_pending_traps(received_items, id_to_item_name, trap_names, already_fired):
    """How many *new* trap instances need to fire, given what's been received and the
    persisted ``already_fired`` cursor.

    ``received_items`` is the client's append-only list of AP item packets (dicts with an
    ``"item"`` id). We resolve each id to a name via ``id_to_item_name`` and count those whose
    name is in ``trap_names``, then subtract the count we've already acted on. Mirrors
    ``check_victory``'s count-by-id idempotency, but persisted: on a reconnect or app restart
    the server replays the full backlog, so recounting against the saved cursor yields 0 for
    traps already handled — they never re-fire. Pure (no Kivy) so it tests headlessly."""
    if not trap_names:
        return 0
    seen = 0
    for item in received_items:
        name = id_to_item_name.get(item.get("item"))
        if name in trap_names:
            seen += 1
    return max(0, seen - already_fired)


# --- Shuffle Trap selection (pure; used by the client's Shuffle Trap effect) ---
def eligible_shuffle_tracks(track_progress, owned_albums):
    """URIs of tracks a Shuffle Trap may replay: already finished AND still owned.

    ``track_progress`` maps track-uri -> dict with ``is_finished`` and ``parent_uri`` (the
    album). The Shuffle Trap force-replays tracks the player has actually heard, so we only
    ever pick finished tracks whose parent album is unlocked. Replaying a finished track awards
    nothing new (``complete_track`` no-ops on finished tracks) and never reveals an unheard
    track in hidden mode. Pure (no Kivy) so it tests headlessly."""
    return [
        uri
        for uri, data in track_progress.items()
        if data.get("is_finished") and data.get("parent_uri") in owned_albums
    ]


def pick_shuffle_tracks(pool, n, rng):
    """Pick up to ``n`` distinct URIs from ``pool`` using ``rng`` (a ``random.Random``).

    Returns ``[]`` for an empty pool or non-positive ``n``; otherwise a sample of
    ``min(n, len(pool))`` distinct entries. Pure/deterministic under a seeded ``rng``."""
    if not pool or n <= 0:
        return []
    return rng.sample(list(pool), min(n, len(pool)))


# --- Track origin (pure; a Mixtape track's real album name + cover) ---
def now_playing_album(track):
    """The album label to show for ``track``: its real source album if it was regrouped into a
    Mixtape, else its own ``album_title``. ``track`` is any object with those attrs. Pure."""
    return getattr(track, "source_album", "") or getattr(track, "album_title", "") or ""


def resolve_track_art(track, container_art):
    """Best art for ``track``: its origin album cover (set on Mixtape tracks) if present, else
    the container album's art, else the generic placeholder. ``container_art`` is the displayed
    album's image. Pure (no Kivy)."""
    return getattr(track, "source_image_url", "") or container_art or KIVY_ICON


# --- Album-pane art masking (A3b; pure; hide a Mixtape collage until completed) ---
def album_art_for_display(image_url, hidden, all_finished):
    """Album-pane cover to show. In hidden mode an unfinished album hides its cover (a Mixtape
    collage is built from its songs' covers, so it spoils contents) behind the neutral placeholder
    until ALL its tracks are finished, at which point the real cover unlocks. Outside hidden mode
    (or once finished) shows the real art. Unowned rows render the LOCKED tile via the kv ownership
    gate regardless, so this value only surfaces once owned. Pure (no Kivy) so it tests headlessly."""
    if hidden and not all_finished:
        return KIVY_ICON
    return image_url


# --- Stats panel (pure; aggregate progress / listening / AP stats) ---
def format_hms(ms):
    """Format a duration in ms as ``H:MM:SS`` (or ``MM:SS`` under an hour). Unlike
    ``RootLayout.format_duration`` this does NOT wrap at 60 minutes, so it suits multi-hour
    aggregate totals (time-left / library total). Negative or non-numeric -> "00:00". Pure."""
    try:
        total = int(ms) // 1000
    except (TypeError, ValueError):
        return "00:00"
    if total < 0:
        return "00:00"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


def compute_stats(
    *,
    track_progress,
    album_data_cache,
    owned_albums,
    ordered_album_uris,
    checked_locations,
    missing_locations,
    received_items,
    id_to_item_name,
    current_album_uri=None,
):
    """Aggregate client stats as a flat dict. Pure: joins per-track flags (``track_progress``) with
    per-track durations (``album_data_cache[uri].tracks[].duration_ms``) and AP location/item
    state. All counts/sums default to 0 on empty input (never divides by zero). No Kivy."""
    track_progress = track_progress or {}
    album_data_cache = album_data_cache or {}
    owned_albums = owned_albums or set()
    ordered_album_uris = ordered_album_uris or []
    checked = checked_locations or set()
    missing = missing_locations or set()
    received_items = received_items or []
    id_to_item_name = id_to_item_name or {}

    # Core: checks (AP truth) + albums.
    checks_found = len(checked)
    checks_total = len(checked) + len(missing)
    checks_pct = round(100 * checks_found / checks_total) if checks_total else 0
    albums_unlocked = len(owned_albums)
    albums_total = len(ordered_album_uris)

    # Listening time + extras: walk the library tracks once (join with progress).
    ms_listened = ms_left = ms_total = ms_left_playable = 0
    durations = []
    finished_per_album = {}
    for album_uri, album in album_data_cache.items():
        for t in getattr(album, "tracks", None) or []:
            d = getattr(t, "duration_ms", 0) or 0
            ms_total += d
            durations.append(d)
            prog = track_progress.get(getattr(t, "uri", None)) or {}
            if prog.get("is_finished"):
                ms_listened += d
                finished_per_album[album_uri] = finished_per_album.get(album_uri, 0) + 1
            else:
                ms_left += d
                if (prog.get("parent_uri") or album_uri) in owned_albums:
                    ms_left_playable += d

    track_count = len(durations)
    track_avg_ms = round(sum(durations) / track_count) if track_count else 0

    # AP details.
    hints_active = sum(1 for p in track_progress.values() if (p or {}).get("hint_text") is not None)
    albums_finished = sum(
        1 for it in received_items if id_to_item_name.get(it.get("item")) == "Album finished!"
    )

    # Current displayed/playing album progress.
    cur_total = cur_finished = cur_ms_total = cur_ms_left = 0
    cur_album = album_data_cache.get(current_album_uri) if current_album_uri else None
    if cur_album:
        for t in getattr(cur_album, "tracks", None) or []:
            d = getattr(t, "duration_ms", 0) or 0
            cur_total += 1
            cur_ms_total += d
            if (track_progress.get(getattr(t, "uri", None)) or {}).get("is_finished"):
                cur_finished += 1
            else:
                cur_ms_left += d

    return {
        "checks_found": checks_found,
        "checks_total": checks_total,
        "checks_pct": checks_pct,
        "albums_unlocked": albums_unlocked,
        "albums_total": albums_total,
        "ms_listened": ms_listened,
        "ms_left": ms_left,
        "ms_total": ms_total,
        "ms_left_playable": ms_left_playable,
        "items_received": len(received_items),
        "hints_active": hints_active,
        "albums_finished": albums_finished,
        "victory": albums_total > 0 and albums_finished >= albums_total,
        "track_count": track_count,
        "track_longest_ms": max(durations) if durations else 0,
        "track_shortest_ms": min(durations) if durations else 0,
        "track_avg_ms": track_avg_ms,
        "mixtapes_touched": len([k for k, v in finished_per_album.items() if v > 0]),
        "current_album_total": cur_total,
        "current_album_finished": cur_finished,
        "current_album_ms_total": cur_ms_total,
        "current_album_ms_left": cur_ms_left,
    }


def build_stats_rows(stats):
    """Ordered display rows for the stats panel: a list of ``{label, value, kind}`` where ``kind``
    is "header" or "stat". Pure; the panel renders this verbatim (so the shown set is data-driven).
    Durations formatted via ``format_hms``."""
    s = stats
    cur = ""
    if s["current_album_total"]:
        cur = (
            f"{s['current_album_finished']} / {s['current_album_total']}  "
            f"({format_hms(s['current_album_ms_left'])} left)"
        )
    sections = [
        (
            "Progress",
            [
                (
                    "Checks found",
                    f"{s['checks_found']} / {s['checks_total']}  ({s['checks_pct']}%)",
                ),
                ("Albums unlocked", f"{s['albums_unlocked']} / {s['albums_total']}"),
                ("Albums finished", f"{s['albums_finished']} / {s['albums_total']}"),
            ],
        ),
        (
            "Listening",
            [
                ("Time left", format_hms(s["ms_left"])),
                ("Playable now", format_hms(s["ms_left_playable"])),
                ("Time listened", format_hms(s["ms_listened"])),
                ("Library total", format_hms(s["ms_total"])),
            ],
        ),
        (
            "Archipelago",
            [
                ("Items received", str(s["items_received"])),
                ("Hints active", str(s["hints_active"])),
                ("Victory", "Yes" if s["victory"] else "No"),
            ],
        ),
        (
            "Extras",
            [
                *([("Current album", cur)] if cur else []),
                ("Tracks", str(s["track_count"])),
                ("Longest track", format_hms(s["track_longest_ms"])),
                ("Shortest track", format_hms(s["track_shortest_ms"])),
                ("Avg track", format_hms(s["track_avg_ms"])),
                ("Mixtapes touched", str(s["mixtapes_touched"])),
            ],
        ),
    ]
    rows = []
    for title, stat_list in sections:
        rows.append({"label": title, "value": "", "kind": "header"})
        for label, value in stat_list:
            rows.append({"label": label, "value": value, "kind": "stat"})
    return rows


def clamp_panel_width(w, lo, hi):
    """Clamp a panel width to ``[lo, hi]`` (for the stats drag handle). Pure."""
    try:
        w = float(w)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, w))


# --- Now-playing highlight (pure; flag the active row for blue coloring) ---
def mark_active_rows(rows, active_uri):
    """Set ``is_playing_now`` True on the row whose ``raw_uri`` matches ``active_uri``, False on
    all others. ``rows`` is a list of RecycleView data dicts. Returns True if any flag changed
    (so the caller can skip a redundant refresh). A falsy ``active_uri`` clears every row.
    Pure (no Kivy) so it tests headlessly."""
    changed = False
    for row in rows:
        want = bool(active_uri) and row.get("raw_uri") == active_uri
        if row.get("is_playing_now") != want:
            row["is_playing_now"] = want
            changed = True
    return changed


# --- Boon selection (A8; pure; used by the client's Skip/Reveal Token effects) ---
def eligible_skip_tracks(track_progress, owned_albums):
    """URIs of tracks a Skip Token may auto-complete: owned but NOT yet finished.

    The inverse of ``eligible_shuffle_tracks`` — a Skip Token releases the check of a track you
    haven't finished, so we only offer owned tracks still missing their check. Returns ``[]``
    when everything owned is finished (the effect then falls back to the modal — never a silent
    no-op). Pure (no Kivy) so it tests headlessly."""
    return [
        uri
        for uri, data in track_progress.items()
        if not data.get("is_finished") and data.get("parent_uri") in owned_albums
    ]


# --- Cross-album auto-advance (extends D7; pure) ---
def first_unfinished_track(album, track_progress):
    """URI of the first track in ``album`` not yet finished (per ``track_progress``), else None.
    ``album`` is any object exposing ``.tracks`` (objects with ``.uri``). Pure (no Kivy)."""
    for t in getattr(album, "tracks", None) or []:
        uri = getattr(t, "uri", None)
        if uri and not (track_progress.get(uri) or {}).get("is_finished"):
            return uri
    return None


def next_album_start(
    ordered_album_uris, current_album_uri, owned_albums, album_data_cache, track_progress
):
    """Where to continue when an album finishes: the next OWNED album (catalog order, wrapping
    past the end) that still has an unfinished track, as ``(album_uri, track_uri)`` — or None when
    every owned album is fully finished. The just-finished album has no unfinished tracks so it is
    naturally skipped. Mirrors the eligible_* selectors (pure dict/list params)."""
    uris = list(ordered_album_uris or [])
    if not uris:
        return None
    try:
        start = uris.index(current_album_uri)
    except ValueError:
        start = -1  # current not in the list -> scan from the top
    n = len(uris)
    for off in range(1, n + 1):
        cand = uris[(start + off) % n]
        if cand not in (owned_albums or set()):
            continue
        album = (album_data_cache or {}).get(cand)
        if not album:
            continue
        track_uri = first_unfinished_track(album, track_progress)
        if track_uri:
            return (cand, track_uri)
    return None


# --- Seek Trap (pure; used by the client's Seek/Scrub Trap effect) ---
def seek_trap_target(pos, dur, delta, end_margin=2.0):
    """Bounds-clamped seek target (seconds) for the Seek Trap.

    ``pos``/``dur`` are the current playhead position and track duration in seconds; ``delta``
    is a signed offset (negative = back-seek/replay, positive = forward-seek/skip). A back-seek
    floors at 0 (no underflow). A forward-seek clamps to ``dur - end_margin`` (not ``dur``) so
    the track still plays out its tail and finishes *naturally* — ``on_playback_finished`` then
    releases the AP check, so the trap can never skip a track's check or seek past the end. When
    ``dur`` is unknown (VLC returns 0 until the stream is parsed) only the 0 floor applies.
    Pure (no Kivy) so it tests headlessly."""
    target = (pos or 0.0) + (delta or 0.0)
    if not dur or dur <= 0:
        return max(0.0, target)
    hi = max(0.0, dur - end_margin)
    return max(0.0, min(target, hi))


# --- Continuous playback (D7; pure helper for the client's auto-advance) ---
def build_continuation_queue(album, track_uri):
    """Album's tracks from the clicked track through the end of the album (inclusive).

    A single-track click should auto-advance through the rest of its album instead of
    stopping after one track. ``album`` is any object exposing ``.tracks`` (a list of objects
    with ``.uri``); works identically for real and meta/Mixtape albums since both are
    ``GenericAlbum`` with a populated ``.tracks``. Returns ``[]`` if ``track_uri`` isn't found
    so the caller can fall back to single-track playback (never softlock). Pure (no Kivy)."""
    tracks = list(getattr(album, "tracks", None) or [])
    for i, t in enumerate(tracks):
        if getattr(t, "uri", None) == track_uri:
            return tracks[i:]
    return []


# --- Message log / chat console (B4; pure helpers for the client's feed) ---
def compose_printjson_text(data_parts, resolve):
    """Compose one display string from an AP ``PrintJSON`` packet's ``data`` parts.

    Each part is a dict whose ``type`` selects rendering:
      - ``player_id`` / ``item_id`` / ``location_id`` -> ``resolve(part_type, text, part)``
        (the client delegates to ``get_ap_info`` for the id->name lookup)
      - anything else (or no type) -> the raw ``text``
    Any exception from ``resolve`` falls back to the raw ``text`` — matching the original
    inline behavior exactly. Non-dict parts are skipped. Pure (no Kivy) so it tests
    headlessly."""
    message_text = ""
    for part in data_parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text", "")
        part_type = part.get("type")
        try:
            if part_type in ("player_id", "item_id", "location_id"):
                message_text += resolve(part_type, text, part)
            else:
                message_text += text
        except Exception:
            message_text += text
    return message_text


# AP's GUI color scheme (hex), copied from Archipelago's NetUtils.JSONtoTextParser so the
# feed matches what its own clients show.
AP_COLOR_CODES = {
    "black": "000000",
    "red": "EE0000",
    "green": "00FF7F",
    "yellow": "FAFAD2",
    "blue": "6495ED",
    "magenta": "EE00EE",
    "cyan": "00EEEE",
    "slateblue": "6D8BE8",
    "plum": "AF99EF",
    "salmon": "FA8072",
    "white": "FFFFFF",
    "orange": "FF7700",
}

# Same color names, darkened for legibility on a LIGHT background (the dark hexes above wash
# out on light — e.g. pale yellow / white / bright cyan vanish). Used when theme == "light".
AP_COLOR_CODES_LIGHT = {
    "black": "000000",
    "red": "C00000",
    "green": "1A7A3A",
    "yellow": "9A7D00",
    "blue": "2A52BE",
    "magenta": "A000A0",
    "cyan": "0A8A8A",
    "slateblue": "3D5BA8",
    "plum": "7D4FBB",
    "salmon": "C0392B",
    "white": "333333",
    "orange": "C75000",
}


def ap_color_codes(theme_name):
    """Pick the AP markup color map for the active theme: the light-tuned map for ``"light"``,
    otherwise the dark map. Pure."""
    return AP_COLOR_CODES_LIGHT if str(theme_name).lower() == "light" else AP_COLOR_CODES


def _escape_kivy_markup(text):
    """Escape Kivy markup metacharacters so literal brackets in item/track names
    (e.g. ``[Radio Edit]``) aren't parsed as tags. Mirrors ``kivy.utils.escape_markup``
    but kept dependency-free so it tests headlessly."""
    return str(text).replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")


def _item_flag_color(flags):
    """AP item color by classification flags (progression / useful / trap / filler)."""
    if flags & 0b001:  # advancement / progression
        return "plum"
    if flags & 0b010:  # useful
        return "slateblue"
    if flags & 0b100:  # trap
        return "salmon"
    return "cyan"  # filler / no flags


def _part_color_name(part, self_slot):
    """AP color name for one PrintJSON part, or ``None`` for uncolored plain text.
    Mirrors NetUtils.JSONtoTextParser's per-type handlers."""
    ptype = part.get("type")
    if ptype in ("item_id", "item_name"):
        return _item_flag_color(part.get("flags", 0) or 0)
    if ptype == "player_id":
        try:
            return "magenta" if int(part.get("text")) == self_slot else "yellow"
        except (TypeError, ValueError):
            return "yellow"
    if ptype == "player_name":
        return "yellow"
    if ptype in ("location_id", "location_name"):
        return "green"
    if ptype == "entrance_name":
        return "blue"
    if ptype == "color":
        return part.get("color")
    return None


def printjson_markup(data_parts, resolve, self_slot=None, color_codes=AP_COLOR_CODES):
    """Compose a Kivy-markup string from a PrintJSON ``data`` parts list, coloring each
    part the way Archipelago's own clients do: items by progression/useful/trap/filler,
    player names (your own magenta vs others' yellow via ``self_slot``), locations green,
    entrances blue. ``resolve(part_type, text, part)`` resolves the ``*_id`` parts to names
    (the same resolver ``compose_printjson_text`` uses). ``color_codes`` is the name->hex map
    for the active theme (default: the dark map; pass ``ap_color_codes(theme_name)`` for the
    light variant). Pure (no Kivy) so it tests headlessly."""
    out = []
    for part in data_parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text", "")
        part_type = part.get("type")
        try:
            if part_type in ("player_id", "item_id", "location_id"):
                text = resolve(part_type, text, part)
        except Exception:
            text = part.get("text", "")
        escaped = _escape_kivy_markup(text)
        color = _part_color_name(part, self_slot)
        hexcode = color_codes.get(color) if color else None
        out.append(f"[color={hexcode}]{escaped}[/color]" if hexcode else escaped)
    return "".join(out)


def make_log_entry(text):
    """A RecycleView row dict for the message feed. ``text`` is Kivy-markup (per-part
    AP coloring), rendered by a ``markup: True`` label."""
    return {"text": text}


def append_capped(entries, entry, cap=200):
    """Append ``entry`` to ``entries`` in place, trimming oldest so it never exceeds
    ``cap`` rows — keeps a long session's feed from growing unbounded. Returns
    ``entries``. Mutating in place keeps Kivy's ``ListProperty`` binding live."""
    entries.append(entry)
    if cap is not None and len(entries) > cap:
        del entries[: len(entries) - cap]
    return entries


# --- Hidden-mode row reveal (pure; used by the client's hidden/guess feature) ---
def unmask_row(track_data):
    """Restore a masked track row's real title/artist/location line and cover art in place.

    In hidden ("unknown song") / guess mode the row is built with title, artist, location
    line, and cover art replaced by placeholders; the real values are stashed under the
    raw_* keys. This restores them — called on track finish and on Reveal. Pure dict
    transform (no Kivy) so it tests headlessly."""
    track_data["text_line_1"] = track_data.get("raw_title", track_data["text_line_1"])
    track_data["text_line_4"] = track_data.get("raw_artist", track_data["text_line_4"])
    if "raw_line3" in track_data:
        track_data["text_line_3"] = track_data["raw_line3"]
    if "raw_image_source" in track_data:
        track_data["image_source"] = track_data["raw_image_source"]


# --- D5 reveal-hotkey peek (pure; a *toggleable, reversible* reveal of the playing track) ---
# A peek differs from a real reveal (finish / Reveal button) in that it must snap back to hidden.
# We stash the masked display under ``_peek_masked`` and flag ``_peeked`` so only peeked rows are
# ever re-hidden — a properly-revealed row drops these markers via ``clear_peek_state``.
_PEEK_MASKED_KEYS = ("text_line_1", "text_line_3", "text_line_4", "image_source")


def peek_reveal_row(track_data):
    """Temporarily reveal a masked row: stash its masked display, mark it peeked, then unmask.
    Pure dict transform (no Kivy) so it tests headlessly."""
    track_data["_peek_masked"] = {k: track_data.get(k) for k in _PEEK_MASKED_KEYS}
    track_data["_peeked"] = True
    unmask_row(track_data)


def peek_rehide_row(track_data):
    """Undo a peek: restore the stashed masked display and drop the peek markers. Pure."""
    masked = track_data.pop("_peek_masked", None)
    track_data.pop("_peeked", None)
    if masked:
        track_data.update(masked)


def clear_peek_state(track_data):
    """Drop the peek markers WITHOUT re-masking. Called when a row is *properly* revealed
    (finished / Reveal) so a later peek-toggle can never re-hide a genuinely-revealed row. Pure."""
    track_data.pop("_peek_masked", None)
    track_data.pop("_peeked", None)
