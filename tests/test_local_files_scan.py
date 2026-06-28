"""Tests for the Local Files scan + bulk-import logic (scan-root onboarding fix).

Kivy widgets can't be instantiated headless, so host/container *logic* is tested
by binding the real methods onto plain stubs via ``types.MethodType``.
"""

import os
import types

import musipelago.musipelago_apworld_gen as g
import musipelago.plugins.local_files_backend as lf
from musipelago.backends import GenericAlbum

# --- _scan_one_dir: extension filter + file discovery ---------------------


def _scanner():
    stub = types.SimpleNamespace(VALID_AUDIO_EXTS=lf.LocalFilesHostUI.VALID_AUDIO_EXTS)
    stub._scan_one_dir = types.MethodType(lf.LocalFilesHostUI._scan_one_dir, stub)
    return stub


def test_scan_one_dir_counts_audio_and_skips_others(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"")
    (tmp_path / "b.flac").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("nope")
    (tmp_path / "cover.jpg").write_bytes(b"")

    track_info, alb, art = _scanner()._scan_one_dir(str(tmp_path))

    paths = sorted(os.path.basename(p) for p, *_ in track_info)
    assert paths == ["a.mp3", "b.flac"]  # only audio, txt/jpg skipped
    # empty/untagged files -> no consensus tags, no crash
    assert alb == "" and art == ""


def test_scan_one_dir_empty_folder(tmp_path):
    track_info, alb, art = _scanner()._scan_one_dir(str(tmp_path))
    assert track_info == [] and alb == "" and art == ""


# --- _build_album: relative-URI construction ------------------------------


def _host_with_root(root):
    stub = types.SimpleNamespace(backend=types.SimpleNamespace(root_directory=root))
    stub._build_album = types.MethodType(lf.LocalFilesHostUI._build_album, stub)
    return stub


def test_parse_track_no_cases():
    assert lf.parse_track_no("5") == 5
    assert lf.parse_track_no("05") == 5
    assert lf.parse_track_no("7/12") == 7  # "n/total" form
    assert lf.parse_track_no("") is None
    assert lf.parse_track_no(None) is None
    assert lf.parse_track_no("bonus") is None


def test_sort_track_infos_prefers_numbered_filenames_over_messy_tags():
    # Reissue case: filenames are 01..03 but tag tracknumbers are duplicated/restarted.
    items = [
        ("03. C.ogg", 1, None, "C"),
        ("01. A.ogg", 1, None, "A"),
        ("02. B.ogg", 2, None, "B"),
    ]
    assert lf.sort_track_infos(items) == ["A", "B", "C"]


def test_sort_track_infos_uses_unique_tags_when_no_filename_numbers():
    items = [
        ("Outro.ogg", 3, None, "z"),
        ("Intro.ogg", 1, None, "x"),
        ("Middle.ogg", 2, None, "y"),
    ]
    assert lf.sort_track_infos(items) == ["x", "y", "z"]


def test_sort_track_infos_falls_back_to_filename():
    items = [("b.ogg", None, None, "b"), ("a.ogg", None, None, "a")]
    assert lf.sort_track_infos(items) == ["a", "b"]


def test_scan_one_dir_orders_untagged_by_filename(tmp_path):
    # Untagged files (no track number) must fall back to filename order, not the
    # arbitrary os.listdir() order.
    for fn in ("03 third.mp3", "01 first.mp3", "02 second.mp3", "skip.txt"):
        (tmp_path / fn).write_bytes(b"")
    track_info, _, _ = _scanner()._scan_one_dir(str(tmp_path))
    names = [os.path.basename(p) for p, *_ in track_info]
    assert names == ["01 first.mp3", "02 second.mp3", "03 third.mp3"]


def test_build_album_sets_cover_from_folder(tmp_path):
    src = tmp_path / "Album"
    src.mkdir()
    (src / "cover.jpg").write_bytes(b"x")
    host = _host_with_root(str(tmp_path))
    album = host._build_album([(str(src / "01.mp3"), "T", "A", 1000)], "Album", "A", str(src))
    assert album.display_image_url.endswith("cover.jpg")


def test_build_album_uses_root_relative_uris():
    root = os.path.join("music", "lib")
    source = os.path.join(root, "Cool Album")
    track_info = [
        (os.path.join(source, "01.mp3"), "Song One", "The Band", 180000),
        (os.path.join(source, "02.mp3"), None, None, 0),  # missing tags -> fallbacks
    ]
    album = _host_with_root(root)._build_album(track_info, "Cool Album", "The Band", source)

    assert isinstance(album, GenericAlbum)
    assert album.uri == "Cool Album"  # relpath(source, root)
    assert album.title == "Cool Album" and album.artist == "The Band"
    assert album.total_tracks == 2
    uris = [t.uri for t in album.tracks]
    assert uris == ["Cool Album/01.mp3", "Cool Album/02.mp3"]
    # tag fallbacks: filename for title, album artist for artist
    assert album.tracks[1].title == "02" and album.tracks[1].artist == "The Band"
    assert all(t.album_title == "Cool Album" for t in album.tracks)


# --- add_apworld_item(curate=…): popup vs. direct add ---------------------


def _container():
    stub = types.SimpleNamespace(
        apworld_data=[], _selection_queue=[], _selection_active=False, finalized=[], queued=[]
    )
    stub._finalize_add = lambda a: stub.finalized.append(a)
    stub._show_next_selection = lambda: stub.queued.append(True)
    stub.add_apworld_item = types.MethodType(g.ListContainer.add_apworld_item, stub)
    return stub


def _album(uri="alb", n=3):
    from musipelago.backends import GenericTrack

    tracks = [
        GenericTrack(
            uri=f"{uri}/{i}",
            title=f"t{i}",
            artist="A",
            album_title=uri,
            duration_ms=1000,
            service="local",
        )
        for i in range(n)
    ]
    return GenericAlbum(
        uri=uri,
        title=uri,
        artist="A",
        image_url="",
        total_tracks=n,
        album_type="Album",
        service="local",
        tracks=tracks,
    )


def test_curate_false_adds_whole_album_without_popup():
    c = _container()
    c.add_apworld_item(_album(n=5), curate=False)
    assert len(c.finalized) == 1  # added directly
    assert c.queued == []  # no track-selection popup queued


def test_curate_true_multitrack_queues_selection():
    c = _container()
    c.add_apworld_item(_album(n=5), curate=True)
    assert c.finalized == []  # not added directly
    assert c.queued == [True]  # selection popup queued instead


def test_multifolder_popup_returns_checked_paths():
    import types

    rec = []
    stub = types.SimpleNamespace(
        on_resolve=lambda paths: rec.append(paths),
        _rows=[
            (types.SimpleNamespace(state="down"), "/m/A"),
            (types.SimpleNamespace(state="normal"), "/m/B"),
            (types.SimpleNamespace(state="down"), "/m/C"),
        ],
    )
    stub.dismiss = lambda: None
    stub._import = types.MethodType(lf.MultiFolderPopup._import, stub)
    stub._cancel = types.MethodType(lf.MultiFolderPopup._cancel, stub)
    stub._set_all = types.MethodType(lf.MultiFolderPopup._set_all, stub)

    stub._import()
    assert rec == [["/m/A", "/m/C"]]  # only checked folders

    rec.clear()
    stub._cancel()
    assert rec == [None]  # cancel -> None

    stub._set_all("down")  # bulk toggle
    assert all(b.state == "down" for b, _ in stub._rows)


def test_add_apworld_item_stamps_all_tracks_for_edit():
    c = _container()
    album = _album(n=4)
    c.add_apworld_item(album, curate=False)
    # full track list captured (enables non-lossy Edit later)
    assert [t.uri for t in album._all_tracks] == [t.uri for t in album.tracks]
    assert len(album._all_tracks) == 4
