import hashlib
import json
import os
import statistics
import sys

# dotenv is no longer needed here
from unidecode import unidecode

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

# Placeholder shown for locked (not-yet-unlocked) albums in the client list.
LOCKED_ICON = resource_path(os.path.join("resources", "locked_placeholder.png"))

# --- Corpus / pack stats (pure; used by the gen app's curation strip + preview) ---


def corpus_stats(albums):
    """Aggregate duration/track stats over every track in ``albums`` (a list of
    ``GenericAlbum``). Pure — flattens exactly like ``build_meta_albums``
    (``for album in albums for t in album.tracks``) and joins nothing else.

    Returns a flat dict: ``n_albums, n_tracks, total_ms, mean_ms, median_ms,
    min_ms, max_ms, n_unknown``. Tracks whose ``duration_ms`` is falsy (None/0 —
    e.g. local files without a probed length) count toward ``n_tracks`` and
    ``n_unknown`` but are excluded from every duration statistic; duration stats
    are 0 when no track has a known length (never divides by zero)."""
    n_tracks = 0
    durations = []
    for album in albums:
        for t in album.tracks:
            n_tracks += 1
            d = t.duration_ms or 0
            if d:
                durations.append(d)
    return {
        "n_albums": len(albums),
        "n_tracks": n_tracks,
        "total_ms": sum(durations),
        "mean_ms": int(statistics.fmean(durations)) if durations else 0,
        "median_ms": int(statistics.median(durations)) if durations else 0,
        "min_ms": min(durations) if durations else 0,
        "max_ms": max(durations) if durations else 0,
        "n_unknown": n_tracks - len(durations),
    }


def pack_layout_summary(albums):
    """Per-pack layout stats for a list of ``GenericAlbum`` — real albums or the
    synthetic metas from ``build_meta_albums`` (both expose ``.tracks`` with
    ``duration_ms``). Pure. Returns ``n_packs, n_tracks`` and per-pack whole-minute
    durations as ``min_min / median_min / max_min`` (all 0 when empty)."""
    pack_minutes = []
    n_tracks = 0
    for album in albums:
        n_tracks += len(album.tracks)
        pack_minutes.append(sum(t.duration_ms or 0 for t in album.tracks) // 60000)
    return {
        "n_packs": len(albums),
        "n_tracks": n_tracks,
        "min_min": min(pack_minutes) if pack_minutes else 0,
        "median_min": int(statistics.median(pack_minutes)) if pack_minutes else 0,
        "max_min": max(pack_minutes) if pack_minutes else 0,
    }


def format_hm(ms):
    """Compact whole-minute duration for aggregate totals: ``'3h 52m'`` / ``'52m'``
    / ``'0m'``. Rounds down to the minute (matches the per-pack minute math).
    Negative or non-numeric -> ``'0m'``. Pure. For per-track ``M:SS`` / ``H:MM:SS``
    reuse ``utils_client.format_hms``."""
    try:
        total_min = int(ms) // 60000
    except (TypeError, ValueError):
        return "0m"
    if total_min < 0:
        return "0m"
    h, m = divmod(total_min, 60)
    return f"{h}h {m}m" if h else f"{m}m"


# --- Jinja2 Filters ---


def filter_to_ascii(text):
    return unidecode(str(text))


def filter_py_json(value):
    return json.dumps(value)


# --- Local-files cover-art discovery (pure; used by the local_files backend) ---
# Common cover filenames, by stem. We accept .jpg/.jpeg/.png for each, plus any
# file whose name starts with "albumart" (Windows Media Player's AlbumArt*.jpg).
_COVER_STEMS = ("cover", "folder", "album", "front")
_COVER_EXTS = (".jpg", ".jpeg", ".png")


def is_cover_filename(name):
    """True if a filename looks like a standalone album-cover image."""
    low = (name or "").lower()
    if low.startswith("albumart") and low.endswith(_COVER_EXTS):
        return True
    stem, ext = os.path.splitext(low)
    return stem in _COVER_STEMS and ext in _COVER_EXTS


def find_cover_in_dir(dirpath):
    """Return the path to a cover image in dirpath, or '' if none.

    Scans in sorted order so the choice is deterministic (and prefers 'album'/'cover'
    over 'folder'/'front' alphabetically). Pure — only touches the filesystem, no Kivy."""
    if not dirpath or not os.path.isdir(dirpath):
        return ""
    for filename in sorted(os.listdir(dirpath)):
        if is_cover_filename(filename):
            return os.path.join(dirpath, filename)
    return ""


def collect_source_covers(root_dir, track_uris):
    """Ordered, de-duplicated cover paths from the source folders of the given track URIs.

    A meta-album (mixtape) has no folder of its own, but each of its tracks still lives in a
    real source-album folder. We resolve each track's folder and collect its cover — used to
    build a mixtape collage. Pure (filesystem only)."""
    if not root_dir:
        return []
    seen_dirs, covers = set(), []
    for uri in track_uris:
        track_dir = os.path.dirname(os.path.normpath(os.path.join(root_dir, uri)))
        if track_dir in seen_dirs:
            continue
        seen_dirs.add(track_dir)
        cover = find_cover_in_dir(track_dir)
        if cover and cover not in covers:
            covers.append(cover)
    return covers


def build_cover_collage(cover_paths, cache_dir, *, tile=256):
    """Composite up to 4 covers into a 2x2 collage cached under cache_dir; return its path.

    Returns '' if Pillow is unavailable, no covers are given, or compositing fails. Cached by
    a hash of the input paths so it's only built once. Fewer than 4 covers are cycled to fill
    the grid; each tile is center-cropped square."""
    if not cover_paths or not cache_dir:
        return ""
    try:
        from PIL import Image
    except ImportError:
        return ""
    key = hashlib.md5("|".join(cover_paths).encode("utf-8")).hexdigest()
    out_path = os.path.join(cache_dir, f"collage_{key}.jpg")
    if os.path.exists(out_path):
        return out_path
    picks = (cover_paths * 4)[:4]  # cycle to fill all 4 cells
    positions = [(0, 0), (tile, 0), (0, tile), (tile, tile)]
    try:
        canvas = Image.new("RGB", (tile * 2, tile * 2), (20, 22, 26))
        for path, (x, y) in zip(picks, positions):
            im = Image.open(path).convert("RGB")
            w, h = im.size
            side = min(w, h)  # center-crop to a square
            im = im.crop(
                ((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side)
            ).resize((tile, tile))
            canvas.paste(im, (x, y))
        canvas.save(out_path, "JPEG", quality=88)
        return out_path
    except Exception:
        return ""
