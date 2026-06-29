"""Tests for the Seek/Scrub Trap.

Two layers (per the headless-testing notes):
- Pure: ``seek_trap_target`` bounds-clamping, tested directly with no Kivy/VLC.
- Routing: ``LocalFilesClientHost._seek_trap`` / ``on_trap_received`` decision, exercised by
  binding the real methods onto a lightweight stub with a recording ``set_position`` so we never
  touch VLC.
"""

import types

import musipelago.plugins.local_files_backend as lfb
from musipelago.utils_client import seek_trap_target


# --- Pure: seek_trap_target ---
def test_back_seek_floors_at_zero():
    # Replay 15s from 5s in -> would be -10s, floors at 0.
    assert seek_trap_target(5.0, 200.0, -15.0) == 0.0


def test_back_seek_in_range():
    assert seek_trap_target(100.0, 200.0, -15.0) == 85.0


def test_forward_seek_in_range():
    assert seek_trap_target(100.0, 200.0, 15.0) == 115.0


def test_forward_seek_clamps_before_end():
    # Near the end, a forward jump clamps to dur - end_margin so the tail still plays out
    # and the track finishes naturally (releasing its AP check).
    assert seek_trap_target(195.0, 200.0, 30.0, end_margin=2.0) == 198.0


def test_unknown_duration_only_floors():
    # VLC returns dur=0 until the stream is parsed; only the 0 floor applies.
    assert seek_trap_target(10.0, 0.0, 30.0) == 40.0
    assert seek_trap_target(10.0, 0.0, -30.0) == 0.0


def test_none_inputs_safe():
    assert seek_trap_target(None, None, None) == 0.0


# --- Routing: on_trap_received / _seek_trap ---
class _Player:
    def __init__(self, pos, dur):
        self._pos = pos
        self._dur = dur
        self.seeked = []

    def get_position(self):
        return self._pos

    def get_duration(self):
        return self._dur

    def set_position(self, seconds):
        self.seeked.append(seconds)


class _App:
    def __init__(self, player, seek_trap_seconds=15):
        self.audio_player = player
        self.seek_trap_seconds = seek_trap_seconds

    def show_toast(self, *_a):
        pass


def _make_host(app, *, is_playing=True, uri="t1"):
    host = types.SimpleNamespace(app=app, is_playing=is_playing, current_playing_track_uri=uri)
    host.on_trap_received = types.MethodType(lfb.LocalFilesClientHost.on_trap_received, host)
    host._seek_trap = types.MethodType(lfb.LocalFilesClientHost._seek_trap, host)
    host._seek_trap_seconds = types.MethodType(lfb.LocalFilesClientHost._seek_trap_seconds, host)
    return host


def test_seek_trap_with_playing_track_seeks_and_consumes():
    player = _Player(100.0, 200.0)
    host = _make_host(_App(player))
    assert host.on_trap_received("Seek Trap") is True
    assert len(player.seeked) == 1
    # 15s default jump, random direction -> 85.0 or 115.0, both in range.
    assert player.seeked[0] in (85.0, 115.0)


def test_seek_trap_not_playing_falls_through_to_modal():
    player = _Player(100.0, 200.0)
    host = _make_host(_App(player), is_playing=False)
    assert host.on_trap_received("Seek Trap") is False
    assert player.seeked == []


def test_seek_trap_no_current_track_falls_through():
    player = _Player(100.0, 200.0)
    host = _make_host(_App(player), uri=None)
    assert host.on_trap_received("Seek Trap") is False
    assert player.seeked == []


def test_seek_trap_seconds_clamped():
    host = _make_host(_App(_Player(0.0, 0.0), seek_trap_seconds=999))
    assert host._seek_trap_seconds() == 60
    host.app.seek_trap_seconds = 1
    assert host._seek_trap_seconds() == 5
    host.app.seek_trap_seconds = "garbage"
    assert host._seek_trap_seconds() == 15
