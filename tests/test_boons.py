"""Tests for A8 boon items (Reveal Token + Skip Token).

Two layers:
- Pure: ``eligible_skip_tracks`` selection and ``count_pending_traps`` reused with boon names +
  a persisted cursor (the once-only mechanism generalizes to boons).
- Routing: ``LocalFilesClientHost.on_boon_received`` / ``_skip_token`` / ``_reveal_token``
  decisions, exercised by binding the real methods onto a stub with recording root_layout
  methods so we never touch Kivy/VLC.
"""

import types

import musipelago.plugins.local_files_backend as lfb
from musipelago.utils_client import count_pending_traps, eligible_skip_tracks


def _prog(*entries):
    """track_progress dict: each entry is (uri, is_finished, parent_uri)."""
    return {uri: {"is_finished": fin, "parent_uri": parent} for uri, fin, parent in entries}


def _items(*ids):
    return [{"item": i} for i in ids]


# --- Pure: eligible_skip_tracks ---
def test_skip_pool_is_owned_unfinished():
    prog = _prog(("t1", False, "albA"), ("t2", True, "albA"), ("t3", False, "albB"))
    # albA owned, albB not -> only t1 (owned, unfinished). t2 finished, t3 unowned.
    assert eligible_skip_tracks(prog, {"albA"}) == ["t1"]


def test_skip_pool_empty_when_all_finished():
    prog = _prog(("t1", True, "albA"), ("t2", True, "albA"))
    assert eligible_skip_tracks(prog, {"albA"}) == []


# --- Pure: once-only cursor reused for boons ---
BOON = "Skip Token"
ID_MAP = {5: BOON, 7: "[Bandit] [alb1]", 9: "Album finished!", 3: "Reveal Token"}
BOON_NAMES = {BOON, "Reveal Token"}


def test_boon_cursor_fresh_fires():
    assert count_pending_traps(_items(5, 3), ID_MAP, BOON_NAMES, 0) == 2


def test_boon_cursor_reconnect_replays_nothing():
    # App restart/reconnect: backlog replayed, cursor already at 2 -> 0 re-fire.
    assert count_pending_traps(_items(7, 5, 9, 3), ID_MAP, BOON_NAMES, 2) == 0


# --- Routing: on_boon_received ---
class _RootLayout:
    def __init__(self, reveal_ok=True):
        self.completed = []
        self.revealed = []
        self._reveal_ok = reveal_ok

    def complete_track(self, uri):
        self.completed.append(uri)

    def reveal_track_metadata(self, uri):
        self.revealed.append(uri)
        return self._reveal_ok


class _App:
    def __init__(self, prog, owned, hidden_metadata=False):
        self.track_progress = prog
        self.owned_albums = owned
        self.hidden_metadata = hidden_metadata

    def show_toast(self, *_a):
        pass


def _make_host(app, root, *, current_uri=None):
    host = types.SimpleNamespace(app=app, root_layout=root, current_playing_track_uri=current_uri)
    host.on_boon_received = types.MethodType(lfb.LocalFilesClientHost.on_boon_received, host)
    host._skip_token = types.MethodType(lfb.LocalFilesClientHost._skip_token, host)
    host._reveal_token = types.MethodType(lfb.LocalFilesClientHost._reveal_token, host)
    return host


def test_unknown_boon_falls_through():
    host = _make_host(_App({}, set()), _RootLayout())
    assert host.on_boon_received("Mystery Token") is False


def test_skip_token_completes_one_unfinished():
    app = _App(_prog(("t1", False, "albA"), ("t2", True, "albA")), {"albA"})
    root = _RootLayout()
    host = _make_host(app, root)
    assert host.on_boon_received("Skip Token") is True
    assert root.completed == ["t1"]


def test_skip_token_prefers_playing_track():
    app = _App(_prog(("t1", False, "albA"), ("t2", False, "albA")), {"albA"})
    root = _RootLayout()
    host = _make_host(app, root, current_uri="t2")
    assert host.on_boon_received("Skip Token") is True
    assert root.completed == ["t2"]


def test_skip_token_empty_pool_falls_through():
    app = _App(_prog(("t1", True, "albA")), {"albA"})
    root = _RootLayout()
    host = _make_host(app, root)
    assert host.on_boon_received("Skip Token") is False
    assert root.completed == []


def test_reveal_token_requires_hidden_mode():
    app = _App(_prog(("t1", False, "albA")), {"albA"}, hidden_metadata=False)
    root = _RootLayout()
    host = _make_host(app, root, current_uri="t1")
    assert host.on_boon_received("Reveal Token") is False
    assert root.revealed == []


def test_reveal_token_reveals_playing_track():
    app = _App(_prog(("t1", False, "albA")), {"albA"}, hidden_metadata=True)
    root = _RootLayout(reveal_ok=True)
    host = _make_host(app, root, current_uri="t1")
    assert host.on_boon_received("Reveal Token") is True
    assert root.revealed == ["t1"]


def test_reveal_token_nothing_playing_falls_through():
    app = _App(_prog(("t1", False, "albA")), {"albA"}, hidden_metadata=True)
    root = _RootLayout()
    host = _make_host(app, root, current_uri=None)
    assert host.on_boon_received("Reveal Token") is False
    assert root.revealed == []


def test_reveal_token_finished_track_falls_through():
    app = _App(_prog(("t1", True, "albA")), {"albA"}, hidden_metadata=True)
    root = _RootLayout()
    host = _make_host(app, root, current_uri="t1")
    assert host.on_boon_received("Reveal Token") is False
    assert root.revealed == []
