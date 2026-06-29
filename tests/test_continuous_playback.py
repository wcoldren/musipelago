"""Tests for D7 continuous playback / auto-advance.

A single-track click should queue from the clicked track through the end of the album currently
shown (real or meta/Mixtape) instead of stopping after one track. The selection logic is the pure
``build_continuation_queue``; the ``_play_track`` wiring and the Shuffle-Trap save/restore
interaction are exercised by binding real methods onto a lightweight stub (per the headless-testing
notes: importing the backend is fine, instantiating Kivy widgets is not).
"""

import types

import musipelago.plugins.local_files_backend as lfb
from musipelago.utils_client import build_continuation_queue


class _Track:
    def __init__(self, uri):
        self.uri = uri


class _Album:
    def __init__(self, tracks, album_type="Album"):
        self.tracks = tracks
        self.album_type = album_type


# --- Pure helper -----------------------------------------------------------------


def test_continuation_from_middle_track():
    alb = _Album([_Track("a"), _Track("b"), _Track("c"), _Track("d")])
    assert [t.uri for t in build_continuation_queue(alb, "b")] == ["b", "c", "d"]


def test_continuation_from_first_track_is_full_album():
    alb = _Album([_Track("a"), _Track("b"), _Track("c")])
    assert [t.uri for t in build_continuation_queue(alb, "a")] == ["a", "b", "c"]


def test_continuation_from_last_track_is_length_one():
    alb = _Album([_Track("a"), _Track("b"), _Track("c")])
    assert [t.uri for t in build_continuation_queue(alb, "c")] == ["c"]


def test_continuation_missing_uri_is_empty():
    alb = _Album([_Track("a"), _Track("b")])
    assert build_continuation_queue(alb, "zzz") == []


def test_continuation_handles_none_album_and_no_tracks():
    assert build_continuation_queue(None, "a") == []
    assert build_continuation_queue(_Album(None), "a") == []


def test_continuation_meta_mixtape_identical():
    """A Mixtape is a plain album with .tracks in the client -> same behavior."""
    mix = _Album([_Track("x"), _Track("y"), _Track("z")], album_type="Mixtape")
    assert [t.uri for t in build_continuation_queue(mix, "y")] == ["y", "z"]


# --- _play_track wiring ----------------------------------------------------------


class _App:
    def __init__(self, cache, container_uri):
        self.album_data_cache = cache
        self._current_track_container_uri = container_uri


def _make_host(app):
    """Stub host with the real ``_play_track`` bound; VLC-touching helpers stubbed out."""
    host = types.SimpleNamespace(app=app, playback_queue=None, queue_index=None, played=[])
    host._play_track = types.MethodType(lfb.LocalFilesClientHost._play_track, host)
    host.stop_polling = lambda: None
    host._cancel_shuffle_trap = lambda: None
    host._play_track_internal = lambda track: host.played.append(track)
    return host


def test_play_track_queues_continuation_to_album_end():
    alb = _Album([_Track("a"), _Track("b"), _Track("c")])
    host = _make_host(_App({"albA": alb}, "albA"))
    host._play_track("b", "B title")
    assert [t.uri for t in host.playback_queue] == ["b", "c"]
    assert host.queue_index == 0
    assert host.played[0].uri == "b"


def test_play_track_unknown_container_falls_back_to_single():
    host = _make_host(_App({}, None))
    host._play_track("solo", "Solo title")
    assert len(host.playback_queue) == 1
    assert host.playback_queue[0].uri == "solo"
    assert host.queue_index == 0


def test_play_track_track_not_in_container_falls_back_to_single():
    alb = _Album([_Track("a"), _Track("b")])
    host = _make_host(_App({"albA": alb}, "albA"))
    host._play_track("not-here", "Orphan")
    assert len(host.playback_queue) == 1
    assert host.playback_queue[0].uri == "not-here"


# --- Shuffle-Trap save/restore over a length>1 continuation queue -----------------


def _make_trap_host(continuation_queue):
    """Stub host with the real ``_start_shuffle_trap``/``_end_shuffle_trap`` bound, primed with
    a multi-track continuation queue mid-album (queue_index pointing at the live track)."""
    host = types.SimpleNamespace(
        app=types.SimpleNamespace(show_toast=lambda *a: None),
        playback_queue=list(continuation_queue),
        queue_index=1,  # currently playing the 2nd track of the continuation
        current_playing_track_uri=continuation_queue[1].uri,
        is_playing=True,
        playback_info_widget=None,
        _trap_playing=False,
        _trap_saved=None,
        _trap_pending=0,
        played=[],
    )
    host._start_shuffle_trap = types.MethodType(lfb.LocalFilesClientHost._start_shuffle_trap, host)
    host._end_shuffle_trap = types.MethodType(lfb.LocalFilesClientHost._end_shuffle_trap, host)
    host._play_track_internal = lambda track: host.played.append(track)
    return host


def test_shuffle_trap_restores_multitrack_continuation_queue():
    cont = [_Track("a"), _Track("b"), _Track("c"), _Track("d")]
    host = _make_trap_host(cont)
    replay = [_Track("old1")]

    host._start_shuffle_trap(replay)
    # Forced replay took over the queue.
    assert [t.uri for t in host.playback_queue] == ["old1"]
    assert host._trap_playing is True

    host._end_shuffle_trap()
    # The original length-4 continuation queue is restored at the interrupted index.
    assert [t.uri for t in host.playback_queue] == ["a", "b", "c", "d"]
    assert host.queue_index == 1
    assert host.played[-1].uri == "b"
    assert host._trap_playing is False
