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


def printjson_markup(data_parts, resolve, self_slot=None):
    """Compose a Kivy-markup string from a PrintJSON ``data`` parts list, coloring each
    part the way Archipelago's own clients do: items by progression/useful/trap/filler,
    player names (your own magenta vs others' yellow via ``self_slot``), locations green,
    entrances blue. ``resolve(part_type, text, part)`` resolves the ``*_id`` parts to names
    (the same resolver ``compose_printjson_text`` uses). Pure (no Kivy) so it tests
    headlessly."""
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
        hexcode = AP_COLOR_CODES.get(color) if color else None
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
