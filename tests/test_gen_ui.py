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


def test_locked_icon_asset_exists():
    import os
    import musipelago.utils as u
    assert os.path.isfile(u.LOCKED_ICON)


def test_client_kv_parses_with_locked_icon_import():
    import os
    from kivy.lang import Builder
    kv = os.path.join(os.path.dirname(g.__file__), "musipelagoclient.kv")
    Builder.load_file(kv)          # exercises the #:import LOCKED_ICON + album-art rule


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


def test_refresh_actions_apworld_multitrack_is_edit():
    s = _row("apworld", _album())          # _album() has 2 tracks
    s._refresh_actions()
    assert s.primary_label == "Edit" and s.has_secondary is True


def test_refresh_actions_apworld_singletrack_is_remove():
    from musipelago.backends import GenericAlbum, GenericTrack
    one = GenericAlbum(uri="a", title="a", artist="A", image_url="", total_tracks=1,
                       album_type="Album", service="local",
                       tracks=[GenericTrack(uri="a/0", title="t", artist="A",
                               album_title="a", duration_ms=1000, service="local")])
    s = _row("apworld", one)
    s._refresh_actions()
    assert s.primary_label == "Remove" and s.has_secondary is False


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
        ("apworld", _album(), "Remove"),   # has_secondary False -> Remove (single-track semantics)
        ("search", _album(), "Add to APWorld"),
        ("search", GenericArtist(uri="ar", name="B", image_url="", service="local"),
         "Show all albums"),
    ]:
        recorded = []
        stub = types.SimpleNamespace(list_id=list_id, generic_item=item, has_secondary=False)
        stub.menu_action = lambda txt, r=recorded: r.append(txt)
        stub.on_primary = types.MethodType(g.CustomListItem.on_primary, stub)
        stub.on_primary()
        assert recorded == [expected], (list_id, recorded)


# --- ListContainer summary ------------------------------------------------

def test_apworld_summary_formats_albums_and_tracks():
    stub = types.SimpleNamespace(list_two_data=[], apworld_summary="", apworld_data=[])
    stub.refresh_apworld_view = types.MethodType(g.ListContainer.refresh_apworld_view, stub)

    stub.apworld_data = [_album("a", 3), _album("b", 2)]
    stub.refresh_apworld_view()
    assert stub.apworld_summary == "Your APWorld — 2 albums · 5 tracks"
    assert len(stub.list_two_data) == 2
    # raw URI is no longer surfaced; line 4 is a duration, not the uri
    assert all(row["text_line_4"] != row["generic_item"].uri for row in stub.list_two_data)

    stub.apworld_data = []
    stub.refresh_apworld_view()
    assert stub.apworld_summary == "Your APWorld — empty"


def test_apworld_summary_singular_grammar():
    stub = types.SimpleNamespace(list_two_data=[], apworld_summary="",
                                 apworld_data=[_album("solo", 1)])
    stub.refresh_apworld_view = types.MethodType(g.ListContainer.refresh_apworld_view, stub)
    stub.refresh_apworld_view()
    assert stub.apworld_summary == "Your APWorld — 1 album · 1 track"


# --- gen_settings persistence (theme + last_directory coexist) -------------

def _app_with_store(tmp_path):
    from kivy.storage.jsonstore import JsonStore
    stub = types.SimpleNamespace(store=JsonStore(str(tmp_path / "gen.json")))
    stub._load_gen_setting = types.MethodType(g.MusipelagoAPWGenApp._load_gen_setting, stub)
    stub._save_gen_setting = types.MethodType(g.MusipelagoAPWGenApp._save_gen_setting, stub)
    return stub


def test_gen_settings_roundtrip_and_defaults(tmp_path):
    app = _app_with_store(tmp_path)
    assert app._load_gen_setting('theme', 'dark') == 'dark'   # missing -> default
    assert app._load_gen_setting('last_directory') is None

    app._save_gen_setting('theme', 'light')
    app._save_gen_setting('last_directory', '/music/lib')
    app._save_gen_setting('last_service', 'local_files_backend')
    app._save_gen_setting('ap_dir', '/opt/Archipelago')
    # all keys coexist (saving one must not clobber the others)
    assert app._load_gen_setting('theme') == 'light'
    assert app._load_gen_setting('last_directory') == '/music/lib'
    assert app._load_gen_setting('last_service') == 'local_files_backend'
    assert app._load_gen_setting('ap_dir') == '/opt/Archipelago'


def test_track_selection_on_ok_reads_toggle_state():
    # TrackSelectionPopup rows are ToggleButtons now; on_ok reads .state.
    recorded = []
    stub = types.SimpleNamespace(
        album="ALBUM",
        on_resolve=lambda alb, states: recorded.append((alb, states)),
        _rows=[(types.SimpleNamespace(state='down'), 't0'),
               (types.SimpleNamespace(state='normal'), 't1'),
               (types.SimpleNamespace(state='down'), 't2')],
    )
    stub.dismiss = lambda: None
    stub.on_ok = types.MethodType(g.TrackSelectionPopup.on_ok, stub)
    stub.on_ok()
    assert recorded == [("ALBUM", [True, False, True])]


# --- _read_meta_config reads ToggleButton state ---------------------------

class _FakeIds(dict):
    """Supports both `'x' in ids` and `ids.x` like Kivy's ids."""
    def __getattr__(self, k):
        return self[k]


def _meta_popup(**widgets):
    stub = types.SimpleNamespace(ids=_FakeIds(widgets))
    stub._read_meta_config = types.MethodType(g.GeneratePopup._read_meta_config, stub)
    return stub


def test_read_meta_config_disabled_when_toggle_up():
    p = _meta_popup(meta_enable=types.SimpleNamespace(state='normal'))
    assert p._read_meta_config() == {'enabled': False}


def test_read_meta_config_reads_toggle_states():
    p = _meta_popup(
        meta_enable=types.SimpleNamespace(state='down'),
        meta_mode=types.SimpleNamespace(text='Minutes per pack'),
        meta_count=types.SimpleNamespace(text='12'),
        meta_seed=types.SimpleNamespace(text=''),
        meta_subset=types.SimpleNamespace(text='8'),
        meta_shuffle=types.SimpleNamespace(state='normal'),
    )
    cfg = p._read_meta_config()
    assert cfg == {'enabled': True, 'mode': 'minutes', 'count': 12, 'seed': None,
                   'subset': 8, 'shuffle': False}


# --- starter YAML + output_root -------------------------------------------

def test_build_starter_yaml_has_game_and_capped_slot():
    y = g.build_starter_yaml("A_Really_Long_World_Name_123")
    assert "game: Musipelago_A_Really_Long_World_Name_123" in y
    assert "name: A_Really_Long_W" in y          # slot capped to 16 chars
    assert "StartingAlbum: album_001" in y
    assert "AllowPlayingAnyTrack: true" in y


def test_output_root_default_and_saved(tmp_path):
    import os
    app = _app_with_store(tmp_path)
    app.output_root = types.MethodType(g.MusipelagoAPWGenApp.output_root, app)
    assert app.output_root() == os.path.expanduser('~/Musipelago')   # default
    app._save_gen_setting('output_dir', '/tmp/worlds')
    assert app.output_root() == '/tmp/worlds'


# --- non-lossy track editing (ListContainer._apply_edit) -------------------

def _edit_container(album):
    stub = types.SimpleNamespace(apworld_data=[album], refreshed=0)
    stub.refresh_apworld_view = lambda: setattr(stub, 'refreshed', stub.refreshed + 1)
    stub._apply_edit = types.MethodType(g.ListContainer._apply_edit, stub)
    return stub


def _full_album(n=3):
    a = _album("alb", n)
    a._all_tracks = list(a.tracks)     # what add_apworld_item stamps
    return a


def test_apply_edit_trims_then_readds_nonlossy(monkeypatch):
    monkeypatch.setattr(g, "App", types.SimpleNamespace(
        get_running_app=lambda: types.SimpleNamespace(root=types.SimpleNamespace(status_text=""))))
    album = _full_album(3)
    c = _edit_container(album)

    # uncheck the middle track
    c._apply_edit(album, [True, False, True])
    assert [t.uri for t in album.tracks] == ["alb/0", "alb/2"]
    assert album.total_tracks == 2 and c.refreshed == 1

    # re-check everything -> the removed track comes back (non-lossy)
    c._apply_edit(album, [True, True, True])
    assert [t.uri for t in album.tracks] == ["alb/0", "alb/1", "alb/2"]
    assert album.total_tracks == 3


def test_apply_edit_cancel_and_empty_are_noops(monkeypatch):
    monkeypatch.setattr(g, "App", types.SimpleNamespace(
        get_running_app=lambda: types.SimpleNamespace(root=types.SimpleNamespace(status_text=""))))
    album = _full_album(3)
    c = _edit_container(album)

    c._apply_edit(album, None)                     # cancel
    assert len(album.tracks) == 3 and c.refreshed == 0

    c._apply_edit(album, [False, False, False])    # empty -> no-op (use Remove)
    assert len(album.tracks) == 3 and c.refreshed == 0
