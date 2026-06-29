"""Pure tests for the track-origin display helpers (now_playing_album / resolve_track_art)."""

import types

from musipelago.utils_client import KIVY_ICON, now_playing_album, resolve_track_art


def _track(**kw):
    base = {"album_title": "Mixtape 03", "source_album": "", "source_image_url": ""}
    base.update(kw)
    return types.SimpleNamespace(**base)


# --- now_playing_album ---
def test_uses_source_album_when_set():
    t = _track(source_album="Eaten Back to Life", album_title="Mixtape 03")
    assert now_playing_album(t) == "Eaten Back to Life"


def test_falls_back_to_album_title():
    t = _track(source_album="", album_title="Real Album")
    assert now_playing_album(t) == "Real Album"


def test_missing_attrs_safe():
    assert now_playing_album(types.SimpleNamespace()) == ""


# --- resolve_track_art ---
def test_prefers_source_image():
    t = _track(source_image_url="/covers/origin.jpg")
    assert resolve_track_art(t, "/covers/mixtape.jpg") == "/covers/origin.jpg"


def test_falls_back_to_container_art():
    t = _track(source_image_url="")
    assert resolve_track_art(t, "/covers/container.jpg") == "/covers/container.jpg"


def test_falls_back_to_placeholder_when_nothing():
    t = _track(source_image_url="")
    assert resolve_track_art(t, "") == KIVY_ICON
    assert resolve_track_art(t, None) == KIVY_ICON
