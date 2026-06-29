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
