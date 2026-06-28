"""Tests for the gen-app UI refresh: theme palettes, kv parse, and the derived
row-action / summary logic.

Kivy widgets can't be instantiated under the dummy SDL driver, so widget *logic*
is tested by binding the real methods onto a plain stub via ``types.MethodType``
(the gen-app methods only touch plain attrs + ``App.get_running_app()``).
"""
import types

import pytest

import musipelago.theme as theme
import musipelago.musipelago_apworld_gen as g
from musipelago.backends import GenericAlbum, GenericArtist, GenericTrack


# --- theme palettes -------------------------------------------------------

def test_palettes_expose_full_key_set_with_valid_rgba():
    for name, pal in theme.PALETTES.items():
        assert set(pal) == set(theme.KEYS), name
        for key in theme.KEYS:
            rgba = pal[key]
            assert len(rgba) == 4, (name, key)
            assert all(0.0 <= c <= 1.0 for c in rgba), (name, key, rgba)


def test_get_palette_is_case_insensitive_and_falls_back_to_dark():
    assert theme.get_palette("LIGHT") is theme.LIGHT
    assert theme.get_palette("dark") is theme.DARK
    assert theme.get_palette("nonsense") is theme.DARK


# --- kv parses ------------------------------------------------------------

def test_gen_kv_parses():
    import os
    from kivy.lang import Builder
    kv = os.path.join(os.path.dirname(g.__file__), "musipelagoapwgen.kv")
    Builder.load_file(kv)          # raises on a malformed rule


# --- CustomListItem derived action affordances ----------------------------

def _row(list_id, item):
    """A plain stub carrying the attrs CustomListItem._refresh_actions touches."""
    stub = types.SimpleNamespace(list_id=list_id, generic_item=item,
                                 primary_label="", has_secondary=False)
    stub._refresh_actions = types.MethodType(g.CustomListItem._refresh_actions, stub)
    return stub


def _album(uri="a", n=2):
    tr = [GenericTrack(uri=f"{uri}/{i}", title=f"t{i}", artist="A",
                       album_title=uri, duration_ms=180000, service="local")
          for i in range(n)]
    return GenericAlbum(uri=uri, title=uri, artist="A", image_url="",
                        total_tracks=n, album_type="Album", service="local", tracks=tr)


def test_refresh_actions_search_album_is_add():
    s = _row("search", _album())
    s._refresh_actions()
    assert s.primary_label == "+ Add" and s.has_secondary is False


def test_refresh_actions_search_artist_is_albums_with_secondary():
    s = _row("search", GenericArtist(uri="ar", name="Band", image_url="", service="local"))
    s._refresh_actions()
    assert s.primary_label == "Albums" and s.has_secondary is True


def test_refresh_actions_apworld_is_remove():
    s = _row("apworld", _album())
    s._refresh_actions()
    assert s.primary_label == "✕ Remove" and s.has_secondary is False


def test_refresh_actions_load_more_button():
    s = _row("load_more_button", None)
    s._refresh_actions()
    assert s.primary_label == "Load more" and s.has_secondary is False


def test_refresh_actions_plugin_row_is_actionable():
    # Regression guard: plugin action rows (e.g. local_files) must get a button.
    s = _row("local_files_action", "create_album_action")
    s._refresh_actions()
    assert s.primary_label == "Open" and s.has_secondary is False


def test_on_primary_routes_plugin_row_to_host(monkeypatch):
    calls = []
    host = types.SimpleNamespace(
        on_item_menu_click=lambda lid, item: calls.append((lid, item)) or True)
    fake_app = types.SimpleNamespace(plugin_host_ui=host)
    monkeypatch.setattr(g, "App", types.SimpleNamespace(get_running_app=lambda: fake_app))

    stub = types.SimpleNamespace(list_id="local_files_action",
                                 generic_item="create_album_action")
    stub.on_primary = types.MethodType(g.CustomListItem.on_primary, stub)
    stub.on_primary()
    assert calls == [("local_files_action", "create_album_action")]


def test_on_primary_dispatches_to_menu_action(monkeypatch):
    monkeypatch.setattr(g, "App", types.SimpleNamespace(get_running_app=lambda: None))
    for list_id, item, expected in [
        ("apworld", _album(), "Remove"),
        ("search", _album(), "Add to APWorld"),
        ("search", GenericArtist(uri="ar", name="B", image_url="", service="local"),
         "Show all albums"),
    ]:
        recorded = []
        stub = types.SimpleNamespace(list_id=list_id, generic_item=item)
        stub.menu_action = lambda txt, r=recorded: r.append(txt)
        stub.on_primary = types.MethodType(g.CustomListItem.on_primary, stub)
        stub.on_primary()
        assert recorded == [expected], (list_id, recorded)


# --- ListContainer summary ------------------------------------------------

def test_apworld_summary_formats_albums_and_tracks():
    stub = types.SimpleNamespace(list_two_data=[], apworld_summary="")
    stub.on_apworld_data = types.MethodType(g.ListContainer.on_apworld_data, stub)

    stub.on_apworld_data(stub, [_album("a", 3), _album("b", 2)])
    assert stub.apworld_summary == "Your APWorld — 2 albums · 5 tracks"
    assert len(stub.list_two_data) == 2
    # raw URI is no longer surfaced; line 4 is a duration, not the uri
    assert all(row["text_line_4"] != row["generic_item"].uri for row in stub.list_two_data)

    stub.on_apworld_data(stub, [])
    assert stub.apworld_summary == "Your APWorld — empty"


def test_apworld_summary_singular_grammar():
    stub = types.SimpleNamespace(list_two_data=[], apworld_summary="")
    stub.on_apworld_data = types.MethodType(g.ListContainer.on_apworld_data, stub)
    stub.on_apworld_data(stub, [_album("solo", 1)])
    assert stub.apworld_summary == "Your APWorld — 1 album · 1 track"
