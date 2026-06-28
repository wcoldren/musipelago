"""Tests for local-files cover-art discovery (B3 follow-up).

`is_cover_filename` / `find_cover_in_dir` live in ``utils`` (pure — only the filesystem,
no Kivy/VLC) and back the local_files backend's `_find_local_art`. They broaden the old
exact-name check (cover.jpg/cover.png/folder.jpg/album.jpg) to the common variants, and the
directory scan is reused for the meta-album (mixtape) cover fallback.
"""

import os

from musipelago.utils import (
    build_cover_collage,
    collect_source_covers,
    find_cover_in_dir,
    is_cover_filename,
)


def test_recognizes_common_cover_names():
    for name in [
        "cover.jpg",
        "Cover.JPG",
        "cover.jpeg",
        "cover.png",
        "folder.jpg",
        "folder.png",
        "album.jpeg",
        "front.png",
        "AlbumArt_Large.jpg",
        "albumart.png",
    ]:
        assert is_cover_filename(name), name


def test_rejects_non_cover_files():
    for name in [
        "track01.mp3",
        "band.jpg",
        "scan.tiff",
        "notes.txt",
        "cover.gif",
        "coverart.bmp",
        "",
        None,
    ]:
        assert not is_cover_filename(name), name


def test_find_cover_returns_path(tmp_path):
    (tmp_path / "cover.jpg").write_bytes(b"x")
    (tmp_path / "01 - song.flac").write_bytes(b"x")
    assert find_cover_in_dir(str(tmp_path)) == str(tmp_path / "cover.jpg")


def test_find_cover_handles_variant_name(tmp_path):
    # the old code would have missed folder.png entirely
    (tmp_path / "folder.png").write_bytes(b"x")
    assert find_cover_in_dir(str(tmp_path)) == str(tmp_path / "folder.png")


def test_find_cover_none_when_no_image(tmp_path):
    (tmp_path / "01 - song.mp3").write_bytes(b"x")
    (tmp_path / "readme.txt").write_bytes(b"x")
    assert find_cover_in_dir(str(tmp_path)) == ""


def test_find_cover_missing_dir():
    assert find_cover_in_dir("/no/such/dir") == ""
    assert find_cover_in_dir("") == ""


def test_find_cover_is_deterministic(tmp_path):
    # multiple covers -> alphabetical first (album < cover < folder), so the choice is stable
    for n in ["folder.jpg", "cover.jpg", "album.jpg"]:
        (tmp_path / n).write_bytes(b"x")
    assert find_cover_in_dir(str(tmp_path)) == str(tmp_path / "album.jpg")


# --- mixtape collage helpers -------------------------------------------------


def _album(tmp_path, name, cover="cover.jpg", tracks=("01.ogg", "02.ogg")):
    """Make a fake album folder with a real (Pillow-readable) cover + track files."""
    from PIL import Image

    d = tmp_path / name
    d.mkdir()
    if cover:
        Image.new("RGB", (300, 300), (123, 50, 50)).save(str(d / cover))
    for t in tracks:
        (d / t).write_bytes(b"x")
    return d


def test_collect_source_covers_dedups_by_folder(tmp_path):
    a = _album(tmp_path, "AlbumA")
    b = _album(tmp_path, "AlbumB")
    # two tracks from A, one from B -> two distinct covers, A first
    uris = ["AlbumA/01.ogg", "AlbumA/02.ogg", "AlbumB/01.ogg"]
    covers = collect_source_covers(str(tmp_path), uris)
    assert covers == [str(a / "cover.jpg"), str(b / "cover.jpg")]


def test_collect_source_covers_skips_artless_folder(tmp_path):
    _album(tmp_path, "NoArt", cover=None)
    assert collect_source_covers(str(tmp_path), ["NoArt/01.ogg"]) == []


def test_build_collage_creates_cached_image(tmp_path):
    from PIL import Image

    cache = tmp_path / "cache"
    cache.mkdir()
    a = _album(tmp_path, "A")
    b = _album(tmp_path, "B")
    covers = [str(a / "cover.jpg"), str(b / "cover.jpg")]
    out = build_cover_collage(covers, str(cache), tile=64)
    assert out and os.path.exists(out)
    with Image.open(out) as im:
        assert im.size == (128, 128)  # 2x2 of 64px tiles
    # cached: same inputs -> same path, and it's reused (mtime unchanged)
    mtime = os.path.getmtime(out)
    assert build_cover_collage(covers, str(cache), tile=64) == out
    assert os.path.getmtime(out) == mtime


def test_build_collage_empty_returns_blank():
    assert build_cover_collage([], "/tmp") == ""
