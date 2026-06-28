"""Logic tests for Feature 1 — per-track selection at album add-time.

Kivy widgets can't be instantiated under the dummy SDL driver, so instead of building
a real ``ListContainer`` we bind its real (unbound) methods onto a plain ``Stub`` and
drive them directly. ``TrackSelectionPopup`` is replaced with a scripted fake that
resolves with preset checkbox states, exercising the queue / filter / dedup logic
without a GUI.
"""

import types

import pytest
from kivy.app import App

import musipelago.musipelago_apworld_gen as g
from musipelago.backends import GenericAlbum, GenericTrack


def track(uri, title, artist="A", dur=1000):
    return GenericTrack(
        uri=uri, title=title, artist=artist, album_title="Alb", duration_ms=dur, service="local"
    )


def album(uri, title, n):
    tracks = [track(f"{uri}/t{i}", f"Track {i}") for i in range(n)]
    return GenericAlbum(
        uri=uri,
        title=title,
        artist="A",
        image_url="",
        total_tracks=n,
        album_type="Album",
        service="local",
        tracks=tracks,
    )


class _Root:
    status_text = ""


class _App:
    root = _Root()


@pytest.fixture(autouse=True)
def _running_app(monkeypatch):
    """``add_apworld_item`` reaches the running app for status text."""
    monkeypatch.setattr(App, "get_running_app", staticmethod(lambda: _App()))


_METHODS = ["add_apworld_item", "_show_next_selection", "_on_selection_resolve", "_finalize_add"]


class Stub:
    """Stand-in for ListContainer: binds the real methods onto a plain object so we
    can test the logic without instantiating a Kivy widget (which needs GL)."""

    def __init__(self):
        self.apworld_data = []  # plain list stands in for ListProperty
        self._selection_queue = []
        self._selection_active = False
        for name in _METHODS:
            setattr(self, name, types.MethodType(getattr(g.ListContainer, name), self))


def fresh():
    return Stub()


def uris(lc):
    return [a.uri for a in lc.apworld_data]


def install_scripted_popup(monkeypatch, script):
    """Replace the popup with one that immediately resolves from ``script`` (a list of
    per-album checkbox-state lists, or ``None`` for cancel), consumed in order."""

    class FakePopup:
        def __init__(self, album, on_resolve, **kw):
            self.album = album
            self.on_resolve = on_resolve

        def open(self):
            states = script.pop(0)
            self.on_resolve(self.album, states)

    monkeypatch.setattr(g, "TrackSelectionPopup", FakePopup)


def test_single_track_album_added_directly():
    lc = fresh()
    lc.add_apworld_item(album("s1", "Single", 1))
    assert uris(lc) == ["s1"]
    assert lc.apworld_data[0].total_tracks == 1


def test_multitrack_uncheck_one_filters_and_updates_total(monkeypatch):
    install_scripted_popup(monkeypatch, [[True, False, True]])  # drop middle
    lc = fresh()
    lc.add_apworld_item(album("m1", "Multi", 3))
    assert uris(lc) == ["m1"]
    a = lc.apworld_data[0]
    assert [t.uri for t in a.tracks] == ["m1/t0", "m1/t2"]
    assert a.total_tracks == 2


def test_uncheck_everything_is_cancel(monkeypatch):
    install_scripted_popup(monkeypatch, [[False, False]])
    lc = fresh()
    lc.add_apworld_item(album("m2", "Multi2", 2))
    assert uris(lc) == []


def test_explicit_cancel_adds_nothing(monkeypatch):
    install_scripted_popup(monkeypatch, [None])
    lc = fresh()
    lc.add_apworld_item(album("m3", "Multi3", 2))
    assert uris(lc) == []


def test_dedup_same_uri_added_twice():
    lc = fresh()
    lc.add_apworld_item(album("s1", "Single", 1))
    lc.add_apworld_item(album("s1", "Single again", 1))
    assert uris(lc) == ["s1"]


def test_bulk_adds_serialize_one_popup_at_a_time(monkeypatch):
    install_scripted_popup(monkeypatch, [[True, True], [True, False]])
    lc = fresh()
    lc.add_apworld_item(album("b1", "Bulk1", 2))
    lc.add_apworld_item(album("b2", "Bulk2", 2))
    assert uris(lc) == ["b1", "b2"]
    assert lc.apworld_data[1].total_tracks == 1
    assert lc._selection_active is False
    assert lc._selection_queue == []


def test_in_flight_dedup_guard(monkeypatch):
    """A duplicate added while the first is in an open popup must not commit twice."""
    PENDING = []

    class DeferPopup:
        def __init__(self, album, on_resolve, **kw):
            self.album = album
            self.on_resolve = on_resolve

        def open(self):
            PENDING.append((self.on_resolve, self.album))

    monkeypatch.setattr(g, "TrackSelectionPopup", DeferPopup)
    lc = fresh()
    lc.add_apworld_item(album("q1", "Q1", 2))  # opens popup, q1 in-flight
    lc.add_apworld_item(album("q1", "Q1 dup", 2))  # second q1 while first pending
    while PENDING:  # drain, resolving all-checked
        resolve, alb = PENDING.pop(0)
        resolve(alb, [True, True])
    assert uris(lc).count("q1") == 1, ("duplicate committed!", uris(lc))
