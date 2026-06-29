"""Routing tests for the Shuffle Trap backend effect (``LocalFilesClientHost.on_trap_received``).

The pure selection logic lives in ``test_traps.py`` (no Kivy). Here we exercise the host's
dispatch *decision* — non-shuffle traps fall through to the modal, an empty already-played pool
falls through too, and a non-empty pool consumes the trap and starts the forced replay. We bind
the real methods onto a lightweight stub (per the headless-testing notes: importing the backend
is fine, instantiating widgets is not) and stub out the VLC-touching ``_start_shuffle_trap``.
"""

import types

import musipelago.plugins.local_files_backend as lfb


def _prog(*entries):
    """track_progress dict: each entry is (uri, is_finished, parent_uri)."""
    return {uri: {"is_finished": fin, "parent_uri": parent} for uri, fin, parent in entries}


class _Track:
    def __init__(self, uri):
        self.uri = uri


class _Album:
    def __init__(self, tracks):
        self.tracks = tracks


class _App:
    def __init__(self, prog, owned, cache, n=1):
        self.track_progress = prog
        self.owned_albums = owned
        self.album_data_cache = cache
        self.shuffle_trap_count = n

    def show_toast(self, *_a):
        pass


def _make_host(app):
    """A stub host with the real routing/resolution methods bound, but a recording
    ``_start_shuffle_trap`` so we never touch VLC."""
    host = types.SimpleNamespace(app=app, _trap_playing=False, _trap_pending=0, started=[])
    host.on_trap_received = types.MethodType(lfb.LocalFilesClientHost.on_trap_received, host)
    host._resolve_trap_tracks = types.MethodType(
        lfb.LocalFilesClientHost._resolve_trap_tracks, host
    )
    host._shuffle_trap_count = types.MethodType(lfb.LocalFilesClientHost._shuffle_trap_count, host)
    host._start_shuffle_trap = lambda tracks: host.started.append(tracks)
    return host


def test_non_shuffle_trap_falls_through_to_modal():
    host = _make_host(_App({}, set(), {}))
    assert host.on_trap_received("Bad Track Trap") is False
    assert host.started == []


def test_empty_pool_falls_through_to_modal():
    # Track exists but isn't finished -> nothing to replay -> let the modal show.
    host = _make_host(_App(_prog(("t1", False, "albA")), {"albA"}, {}))
    assert host.on_trap_received("Shuffle Trap") is False
    assert host.started == []


def test_nonempty_pool_consumes_and_starts_effect():
    tr = _Track("t1")
    app = _App(_prog(("t1", True, "albA")), {"albA"}, {"albA": _Album([tr])})
    host = _make_host(app)
    assert host.on_trap_received("Shuffle Trap") is True
    assert len(host.started) == 1
    assert [t.uri for t in host.started[0]] == ["t1"]


def test_overlapping_trap_serialized_not_double_started():
    tr = _Track("t1")
    app = _App(_prog(("t1", True, "albA")), {"albA"}, {"albA": _Album([tr])})
    host = _make_host(app)
    host._trap_playing = True  # a forced replay is already running
    assert host.on_trap_received("Shuffle Trap") is True
    assert host.started == []  # queued, not started immediately
    assert host._trap_pending == 1
