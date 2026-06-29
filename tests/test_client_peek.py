"""Tests for D5: the Cmd/Ctrl+R reveal hotkey (`RootLayout.peek_playing_track` / `_on_global_key`).

A *peek* reveals the currently-playing track's hidden metadata WITHOUT calling ``complete_track``
— so unlike ``reveal_track`` it never releases an AP check (no guess-mode give-up). Per the
headless notes we bind the real methods onto a stub and monkeypatch ``App.get_running_app``; the
stub deliberately has no ``complete_track``, so a regression that called it would raise.
"""

import types

import musipelago.musipelago_client as mc
from musipelago.utils_client import (
    KIVY_ICON,
    clear_peek_state,
    peek_rehide_row,
    peek_reveal_row,
)


class _RV:
    def __init__(self, data):
        self.data = data
        self.refreshed = 0

    def refresh_from_data(self):
        self.refreshed += 1


def _masked_row(uri="t1"):
    return {
        "raw_uri": uri,
        "text_line_1": "Unknown Track",
        "text_line_4": "Unknown Artist",
        "text_line_3": "???",
        "image_source": KIVY_ICON,
        "raw_title": "Paranoid Android",
        "raw_artist": "Radiohead",
        "raw_line3": "OK Computer - Slot 1",
        "raw_image_source": "/cache/real.jpg",
        "can_reveal": True,
        "can_guess": True,
    }


def _make_root(monkeypatch, rows, playing_uri):
    """Stub RootLayout with the real peek methods bound and a fake app/ids/track_rv."""
    rv = _RV(rows)
    root = types.SimpleNamespace(
        ids=types.SimpleNamespace(
            list_container=types.SimpleNamespace(ids=types.SimpleNamespace(track_rv=rv))
        ),
        toasts=[],
    )
    host = types.SimpleNamespace(current_playing_track_uri=playing_uri)
    app = types.SimpleNamespace(client_host_ui=host, show_toast=lambda m: root.toasts.append(m))
    monkeypatch.setattr(mc.App, "get_running_app", staticmethod(lambda: app))
    root.peek_playing_track = types.MethodType(mc.RootLayout.peek_playing_track, root)
    root._unmask_track_row = mc.RootLayout._unmask_track_row  # staticmethod
    root._rv = rv
    return root


def test_peek_unmasks_playing_row_without_completing(monkeypatch):
    row = _masked_row("t1")
    root = _make_root(monkeypatch, [row], playing_uri="t1")
    root.peek_playing_track()
    assert row["text_line_1"] == "Paranoid Android"
    assert row["text_line_4"] == "Radiohead"
    assert row["image_source"] == "/cache/real.jpg"
    assert root._rv.refreshed == 1
    # Peek is transient: it does NOT collapse the per-row buttons (no give-up).
    assert row["can_reveal"] is True
    assert row["can_guess"] is True
    assert row["_peeked"] is True
    assert any("peek" in t.lower() for t in root.toasts)


def test_peek_toggles_back_to_hidden_on_second_press(monkeypatch):
    row = _masked_row("t1")
    root = _make_root(monkeypatch, [row], playing_uri="t1")
    root.peek_playing_track()  # reveal
    root.peek_playing_track()  # re-hide
    assert row["text_line_1"] == "Unknown Track"
    assert row["text_line_4"] == "Unknown Artist"
    assert row["text_line_3"] == "???"
    assert row["image_source"] == KIVY_ICON
    assert "_peeked" not in row
    assert root._rv.refreshed == 2
    assert any("hidden again" in t.lower() for t in root.toasts)


def test_peek_skips_a_properly_revealed_row(monkeypatch):
    # A finished/revealed row (can_reveal False, not peeked) must not be toggled by the peek.
    row = _masked_row("t1")
    row["can_reveal"] = False  # already properly revealed
    row["text_line_1"] = "Paranoid Android"  # showing real metadata
    root = _make_root(monkeypatch, [row], playing_uri="t1")
    root.peek_playing_track()
    assert row["text_line_1"] == "Paranoid Android"  # untouched, still shown
    assert "_peeked" not in row
    assert root._rv.refreshed == 0
    assert any("already revealed" in t.lower() for t in root.toasts)


def test_peek_with_nothing_playing_toasts_and_no_refresh(monkeypatch):
    row = _masked_row("t1")
    root = _make_root(monkeypatch, [row], playing_uri=None)
    root.peek_playing_track()
    assert row["text_line_1"] == "Unknown Track"  # untouched
    assert root._rv.refreshed == 0
    assert any("nothing is playing" in t.lower() for t in root.toasts)


def test_peek_when_playing_not_in_list(monkeypatch):
    row = _masked_row("t1")
    root = _make_root(monkeypatch, [row], playing_uri="other")
    root.peek_playing_track()
    assert row["text_line_1"] == "Unknown Track"  # untouched
    assert root._rv.refreshed == 0
    assert any("isn't in this list" in t for t in root.toasts)


# --- key routing ---------------------------------------------------------------


def _make_key_root():
    root = types.SimpleNamespace(peeked=0)
    root._on_global_key = types.MethodType(mc.RootLayout._on_global_key, root)
    root.peek_playing_track = lambda: setattr(root, "peeked", root.peeked + 1)
    return root


def test_cmd_r_triggers_peek_and_consumes():
    root = _make_key_root()
    assert root._on_global_key(None, 0, 0, "r", ["meta"]) is True
    assert root.peeked == 1


def test_ctrl_r_triggers_peek():
    root = _make_key_root()
    assert root._on_global_key(None, 0, 0, "r", ["ctrl"]) is True
    assert root.peeked == 1


def test_plain_r_passes_through():
    root = _make_key_root()
    assert root._on_global_key(None, 0, 0, "r", []) is False
    assert root.peeked == 0


def test_other_modified_key_passes_through():
    root = _make_key_root()
    assert root._on_global_key(None, 0, 0, "s", ["ctrl"]) is False
    assert root.peeked == 0


# --- pure peek helpers ---------------------------------------------------------


def test_peek_reveal_then_rehide_round_trips():
    row = _masked_row("t1")
    peek_reveal_row(row)
    assert row["_peeked"] is True
    assert row["text_line_1"] == "Paranoid Android"
    peek_rehide_row(row)
    # Masked display restored exactly; markers gone.
    assert row["text_line_1"] == "Unknown Track"
    assert row["text_line_3"] == "???"
    assert row["text_line_4"] == "Unknown Artist"
    assert row["image_source"] == KIVY_ICON
    assert "_peeked" not in row
    assert "_peek_masked" not in row


def test_clear_peek_state_drops_markers_without_remasking():
    row = _masked_row("t1")
    peek_reveal_row(row)  # now unmasked + flagged
    clear_peek_state(row)
    # Stays revealed (no re-mask), but the peek markers are gone so a toggle won't re-hide it.
    assert row["text_line_1"] == "Paranoid Android"
    assert "_peeked" not in row
    assert "_peek_masked" not in row


def test_rehide_is_noop_without_stashed_mask():
    # Defensive: re-hiding a row that was never peeked must not raise or invent values.
    row = {"text_line_1": "Shown", "raw_uri": "t1"}
    peek_rehide_row(row)
    assert row["text_line_1"] == "Shown"
