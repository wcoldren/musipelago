"""Tests for the gen-app UI refresh: theme palettes, kv parse, and the derived
row-action / summary logic.

Kivy widgets can't be instantiated under the dummy SDL driver, so widget *logic*
is tested by binding the real methods onto a plain stub via ``types.MethodType``
(the gen-app methods only touch plain attrs + ``App.get_running_app()``).
"""

import types

import musipelago.musipelago_apworld_gen as g
import musipelago.theme as theme
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
    Builder.load_file(kv)  # raises on a malformed rule


def test_locked_icon_asset_exists():
    import os

    import musipelago.utils as u

    assert os.path.isfile(u.LOCKED_ICON)


def test_client_kv_parses_with_locked_icon_import():
    import os

    from kivy.lang import Builder

    kv = os.path.join(os.path.dirname(g.__file__), "musipelagoclient.kv")
    Builder.load_file(kv)  # exercises the #:import LOCKED_ICON + album-art rule


# --- CustomListItem derived action affordances ----------------------------


def _row(list_id, item):
    """A plain stub carrying the attrs CustomListItem._refresh_actions touches."""
    stub = types.SimpleNamespace(
        list_id=list_id, generic_item=item, primary_label="", has_secondary=False
    )
    stub._refresh_actions = types.MethodType(g.CustomListItem._refresh_actions, stub)
    return stub


def _album(uri="a", n=2):
    tr = [
        GenericTrack(
            uri=f"{uri}/{i}",
            title=f"t{i}",
            artist="A",
            album_title=uri,
            duration_ms=180000,
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
        tracks=tr,
    )


def test_refresh_actions_search_album_is_add():
    s = _row("search", _album())
    s._refresh_actions()
    assert s.primary_label == "+ Add" and s.has_secondary is False


def test_refresh_actions_search_artist_is_albums_with_secondary():
    s = _row("search", GenericArtist(uri="ar", name="Band", image_url="", service="local"))
    s._refresh_actions()
    assert s.primary_label == "Albums" and s.has_secondary is True


def test_refresh_actions_apworld_multitrack_is_edit():
    s = _row("apworld", _album())  # _album() has 2 tracks
    s._refresh_actions()
    assert s.primary_label == "Edit" and s.has_secondary is True


def test_refresh_actions_apworld_singletrack_is_remove():
    from musipelago.backends import GenericAlbum, GenericTrack

    one = GenericAlbum(
        uri="a",
        title="a",
        artist="A",
        image_url="",
        total_tracks=1,
        album_type="Album",
        service="local",
        tracks=[
            GenericTrack(
                uri="a/0", title="t", artist="A", album_title="a", duration_ms=1000, service="local"
            )
        ],
    )
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
        on_item_menu_click=lambda lid, item: calls.append((lid, item)) or True
    )
    fake_app = types.SimpleNamespace(plugin_host_ui=host)
    monkeypatch.setattr(g, "App", types.SimpleNamespace(get_running_app=lambda: fake_app))

    stub = types.SimpleNamespace(list_id="local_files_action", generic_item="create_album_action")
    stub.on_primary = types.MethodType(g.CustomListItem.on_primary, stub)
    stub.on_primary()
    assert calls == [("local_files_action", "create_album_action")]


def test_on_primary_dispatches_to_menu_action(monkeypatch):
    monkeypatch.setattr(g, "App", types.SimpleNamespace(get_running_app=lambda: None))
    for list_id, item, expected in [
        ("apworld", _album(), "Remove"),  # has_secondary False -> Remove (single-track semantics)
        ("search", _album(), "Add to APWorld"),
        (
            "search",
            GenericArtist(uri="ar", name="B", image_url="", service="local"),
            "Show all albums",
        ),
    ]:
        recorded = []
        stub = types.SimpleNamespace(list_id=list_id, generic_item=item, has_secondary=False)
        stub.menu_action = lambda txt, r=recorded: r.append(txt)
        stub.on_primary = types.MethodType(g.CustomListItem.on_primary, stub)
        stub.on_primary()
        assert recorded == [expected], (list_id, recorded)


# --- ListContainer summary + stats strip ----------------------------------


def _summary_stub(albums):
    stub = types.SimpleNamespace(
        list_two_data=[], apworld_summary="", apworld_warn="", apworld_data=albums
    )
    stub.refresh_apworld_view = types.MethodType(g.ListContainer.refresh_apworld_view, stub)
    stub._update_summary = types.MethodType(g.ListContainer._update_summary, stub)
    stub.included_albums = types.MethodType(g.ListContainer.included_albums, stub)
    stub.set_album_included = types.MethodType(g.ListContainer.set_album_included, stub)
    stub.select_all_albums = types.MethodType(g.ListContainer.select_all_albums, stub)
    return stub


def _album_durs(uri, durs):
    """A GenericAlbum with one track per entry in ``durs`` (its duration_ms)."""
    tr = [
        GenericTrack(
            uri=f"{uri}/{i}",
            title=f"t{i}",
            artist="A",
            album_title=uri,
            duration_ms=d,
            service="local",
        )
        for i, d in enumerate(durs)
    ]
    return GenericAlbum(
        uri=uri,
        title=uri,
        artist="A",
        image_url="",
        total_tracks=len(tr),
        album_type="Album",
        service="local",
        tracks=tr,
    )


def test_apworld_summary_formats_albums_tracks_and_durations():
    # _album() tracks are 180000ms (3:00) each -> 5 tracks = 15m total, avg/range 3:00.
    stub = _summary_stub([_album("a", 3), _album("b", 2)])
    stub.refresh_apworld_view()
    assert stub.apworld_summary == (
        "Your APWorld — 2 albums · 5 tracks · 15m · avg 03:00 · range 03:00–03:00"
    )
    assert stub.apworld_warn == ""
    assert len(stub.list_two_data) == 2
    # raw URI is no longer surfaced; line 4 is a duration, not the uri
    assert all(row["text_line_4"] != row["generic_item"].uri for row in stub.list_two_data)

    stub.apworld_data = []
    stub.refresh_apworld_view()
    assert stub.apworld_summary == "Your APWorld — empty"
    assert stub.apworld_warn == ""


def test_apworld_summary_singular_grammar():
    stub = _summary_stub([_album_durs("solo", [180000])])
    stub.refresh_apworld_view()
    assert stub.apworld_summary == (
        "Your APWorld — 1 album · 1 track · 3m · avg 03:00 · range 03:00–03:00"
    )
    assert stub.apworld_warn == ""


def test_apworld_summary_mixed_durations_and_range():
    # known: 31s, 3:24, 19:47; total 23:42 -> 23m; range 00:31–19:47.
    stub = _summary_stub([_album_durs("a", [31_000, 204_000, 1_187_000])])
    stub.refresh_apworld_view()
    assert stub.apworld_summary == (
        "Your APWorld — 1 album · 3 tracks · 23m · avg 07:54 · range 00:31–19:47"
    )
    assert stub.apworld_warn == ""


def test_apworld_warn_counts_unknown_and_excludes_them_from_stats():
    # one known (3:00) + one unknown (0): duration stats reflect only the known track.
    stub = _summary_stub([_album_durs("a", [180000, 0])])
    stub.refresh_apworld_view()
    assert "· 2 tracks ·" in stub.apworld_summary
    assert "avg 03:00" in stub.apworld_summary
    assert stub.apworld_warn == "· 1 unknown length"


def test_apworld_warn_plural_and_all_unknown_omits_duration_stats():
    stub = _summary_stub([_album_durs("a", [0, 0]), _album_durs("b", [None])])
    stub.refresh_apworld_view()
    # no known durations -> summary stops after the track count.
    assert stub.apworld_summary == "Your APWorld — 2 albums · 3 tracks"
    assert stub.apworld_warn == "· 3 unknown lengths"


# --- album include/exclude selection --------------------------------------


def test_row_dicts_carry_included_flag_default_true():
    stub = _summary_stub([_album("a", 2)])
    stub.refresh_apworld_view()
    assert stub.list_two_data[0]["included"] is True


def test_summary_counts_only_included_albums():
    a, b = _album("a", 3), _album("b", 2)  # 3:00 tracks
    stub = _summary_stub([a, b])
    stub.refresh_apworld_view()
    assert stub.apworld_summary.startswith("Your APWorld — 2 albums · 5 tracks")
    # exclude album b -> "N of M albums" and only a's tracks/duration counted.
    stub.set_album_included(b, False)
    assert stub.apworld_summary.startswith("Your APWorld — 1 of 2 albums · 3 tracks · 9m")


def test_select_none_then_all_updates_rows_and_summary():
    a, b = _album("a", 3), _album("b", 2)
    stub = _summary_stub([a, b])
    stub.select_all_albums(False)
    assert stub.apworld_summary.startswith("Your APWorld — 0 of 2 albums · 0 tracks")
    assert all(row["included"] is False for row in stub.list_two_data)
    stub.select_all_albums(True)
    assert stub.apworld_summary.startswith("Your APWorld — 2 albums · 5 tracks")
    assert all(row["included"] is True for row in stub.list_two_data)


def test_custom_list_item_toggle_included_persists_and_refreshes(monkeypatch):
    album = _album("a", 2)
    container = _summary_stub([album])
    container.refresh_apworld_view()
    fake_app = types.SimpleNamespace(
        root=types.SimpleNamespace(ids=types.SimpleNamespace(list_container=container))
    )
    monkeypatch.setattr(g, "App", types.SimpleNamespace(get_running_app=lambda: fake_app))

    row = types.SimpleNamespace(included=True, generic_item=album)
    row.toggle_included = types.MethodType(g.CustomListItem.toggle_included, row)
    row.toggle_included()
    assert row.included is False
    assert album._included is False
    assert container.apworld_summary.startswith("Your APWorld — 0 of 1 albums")


def test_preview_counts_only_included_albums():
    ids = _Ids(meta_preview=_ctrl(), meta_enable=_ctrl(state="normal"))
    a, b = _album("a", 3), _album("b", 2)
    b._included = False
    stub = _preview_stub([a, b], ids)
    stub._refresh_preview()
    # only album a (3 tracks, 9 min) is carried forward.
    assert stub.preview_text == "Preview (no regrouping): 1 album · 3 tracks · 9 min/album"


# --- GeneratePopup layout preview -----------------------------------------


class _Ids(dict):
    """Stand-in for Kivy's ids: supports both ``ids.foo`` and ``"foo" in ids``."""

    __getattr__ = dict.__getitem__


def _ctrl(**kw):
    return types.SimpleNamespace(**kw)


def _preview_stub(albums, ids):
    stub = types.SimpleNamespace(apworld_data=albums, ids=ids, preview_text="")
    stub._read_meta_config = types.MethodType(g.GeneratePopup._read_meta_config, stub)
    stub._refresh_preview = types.MethodType(g.GeneratePopup._refresh_preview, stub)
    stub.included_albums = types.MethodType(g.GeneratePopup.included_albums, stub)
    stub._format_preview = g.GeneratePopup._format_preview  # staticmethod
    return stub


def test_format_preview_empty_and_enabled_and_disabled():
    fmt = g.GeneratePopup._format_preview
    assert fmt(
        {"n_packs": 0, "n_tracks": 0, "min_min": 0, "median_min": 0, "max_min": 0}, enabled=True
    ) == ("Preview: add albums to see the pack layout.")
    assert (
        fmt(
            {"n_packs": 10, "n_tracks": 68, "min_min": 21, "median_min": 24, "max_min": 26},
            enabled=True,
        )
        == "Preview: 10 packs · 68 tracks · 21–26 min/pack (median 24)"
    )
    assert (
        fmt(
            {"n_packs": 14, "n_tracks": 68, "min_min": 21, "median_min": 24, "max_min": 26},
            enabled=False,
        )
        == "Preview (no regrouping): 14 albums · 68 tracks · 21–26 min/album (median 24)"
    )
    # uniform packs collapse to a single figure (no median)
    assert (
        fmt(
            {"n_packs": 1, "n_tracks": 3, "min_min": 9, "median_min": 9, "max_min": 9}, enabled=True
        )
        == "Preview: 1 pack · 3 tracks · 9 min/pack"
    )


def test_refresh_preview_disabled_summarizes_real_albums():
    ids = _Ids(meta_preview=_ctrl(), meta_enable=_ctrl(state="normal"))
    stub = _preview_stub([_album("a", 3), _album("b", 2)], ids)  # 3min/track
    stub._refresh_preview()
    # album a: 9 min, album b: 6 min -> range 6–9, median 7 (of [6, 9]).
    assert stub.preview_text == (
        "Preview (no regrouping): 2 albums · 5 tracks · 6–9 min/album (median 7)"
    )


def test_refresh_preview_enabled_rolls_and_backfills_blank_seed():
    ids = _Ids(
        meta_preview=_ctrl(),
        meta_enable=_ctrl(state="down"),
        meta_mode=_ctrl(text="N packs"),
        meta_count=_ctrl(text="2"),
        meta_seed=_ctrl(text=""),
        meta_subset=_ctrl(text=""),
        meta_shuffle=_ctrl(state="down"),
        meta_pack_size=_ctrl(text="5"),
        meta_target_min=_ctrl(text=""),
    )
    stub = _preview_stub([_album("a", 3), _album("b", 3)], ids)  # 6 tracks, 3min each
    stub._refresh_preview()
    # 2 packs of 3 tracks -> 9 min each (uniform).
    assert stub.preview_text == "Preview: 2 packs · 6 tracks · 9 min/pack"
    # blank seed was rolled and written back so generation reproduces the preview.
    assert ids.meta_seed.text.isdigit()

    # Re-running with the now-filled seed keeps the same layout (no re-roll surprise).
    kept = ids.meta_seed.text
    stub._refresh_preview()
    assert ids.meta_seed.text == kept
    assert stub.preview_text == "Preview: 2 packs · 6 tracks · 9 min/pack"


# --- gen_settings persistence (theme + last_directory coexist) -------------


def _app_with_store(tmp_path):
    from kivy.storage.jsonstore import JsonStore

    stub = types.SimpleNamespace(store=JsonStore(str(tmp_path / "gen.json")))
    stub._load_gen_setting = types.MethodType(g.MusipelagoAPWGenApp._load_gen_setting, stub)
    stub._save_gen_setting = types.MethodType(g.MusipelagoAPWGenApp._save_gen_setting, stub)
    return stub


def test_gen_settings_roundtrip_and_defaults(tmp_path):
    app = _app_with_store(tmp_path)
    assert app._load_gen_setting("theme", "dark") == "dark"  # missing -> default
    assert app._load_gen_setting("last_directory") is None

    app._save_gen_setting("theme", "light")
    app._save_gen_setting("last_directory", "/music/lib")
    app._save_gen_setting("last_service", "local_files_backend")
    app._save_gen_setting("ap_dir", "/opt/Archipelago")
    # all keys coexist (saving one must not clobber the others)
    assert app._load_gen_setting("theme") == "light"
    assert app._load_gen_setting("last_directory") == "/music/lib"
    assert app._load_gen_setting("last_service") == "local_files_backend"
    assert app._load_gen_setting("ap_dir") == "/opt/Archipelago"


def test_track_selection_on_ok_reads_toggle_state():
    # TrackSelectionPopup rows are ToggleButtons now; on_ok reads .state.
    recorded = []
    stub = types.SimpleNamespace(
        album="ALBUM",
        on_resolve=lambda alb, states: recorded.append((alb, states)),
        _rows=[
            (types.SimpleNamespace(state="down"), "t0"),
            (types.SimpleNamespace(state="normal"), "t1"),
            (types.SimpleNamespace(state="down"), "t2"),
        ],
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
    p = _meta_popup(meta_enable=types.SimpleNamespace(state="normal"))
    assert p._read_meta_config() == {"enabled": False}


def test_read_meta_config_reads_toggle_states():
    p = _meta_popup(
        meta_enable=types.SimpleNamespace(state="down"),
        meta_mode=types.SimpleNamespace(text="Minutes per pack"),
        meta_count=types.SimpleNamespace(text="12"),
        meta_seed=types.SimpleNamespace(text=""),
        meta_subset=types.SimpleNamespace(text="8"),
        meta_shuffle=types.SimpleNamespace(state="normal"),
    )
    cfg = p._read_meta_config()
    assert cfg == {
        "enabled": True,
        "mode": "minutes",
        "count": 12,
        "seed": None,
        "subset": 8,
        "subset_minutes": None,  # meta_subset_min absent -> None
        "shuffle": False,
        "pack_size": None,  # grid-only fields absent -> None
        "target_minutes": None,
    }


def test_read_meta_config_reads_balanced_grid():
    p = _meta_popup(
        meta_enable=types.SimpleNamespace(state="down"),
        meta_mode=types.SimpleNamespace(text="Balanced grid"),
        meta_count=types.SimpleNamespace(text="10"),
        meta_seed=types.SimpleNamespace(text="3"),
        meta_subset=types.SimpleNamespace(text=""),
        meta_shuffle=types.SimpleNamespace(state="down"),
        meta_pack_size=types.SimpleNamespace(text="5"),
        meta_target_min=types.SimpleNamespace(text="20"),
    )
    cfg = p._read_meta_config()
    assert cfg == {
        "enabled": True,
        "mode": "grid",
        "count": 10,
        "seed": 3,
        "subset": None,
        "subset_minutes": None,
        "shuffle": True,
        "pack_size": 5,
        "target_minutes": 20,
    }


def test_read_meta_config_reads_subset_minutes():
    p = _meta_popup(
        meta_enable=types.SimpleNamespace(state="down"),
        meta_mode=types.SimpleNamespace(text="N packs"),
        meta_count=types.SimpleNamespace(text="4"),
        meta_seed=types.SimpleNamespace(text=""),
        meta_subset=types.SimpleNamespace(text=""),
        meta_subset_min=types.SimpleNamespace(text="45"),
        meta_shuffle=types.SimpleNamespace(state="down"),
    )
    cfg = p._read_meta_config()
    assert cfg["subset"] is None and cfg["subset_minutes"] == 45


def test_read_meta_config_grid_blank_target_is_none():
    p = _meta_popup(
        meta_enable=types.SimpleNamespace(state="down"),
        meta_mode=types.SimpleNamespace(text="Balanced grid"),
        meta_count=types.SimpleNamespace(text="10"),
        meta_seed=types.SimpleNamespace(text=""),
        meta_subset=types.SimpleNamespace(text=""),
        meta_shuffle=types.SimpleNamespace(state="down"),
        meta_pack_size=types.SimpleNamespace(text="5"),
        meta_target_min=types.SimpleNamespace(text=""),
    )
    cfg = p._read_meta_config()
    assert cfg["mode"] == "grid" and cfg["pack_size"] == 5 and cfg["target_minutes"] is None


# --- starter YAML + output_root -------------------------------------------


def test_build_starter_yaml_has_game_and_capped_slot():
    y = g.build_starter_yaml("A_Really_Long_World_Name_123")
    assert "game: Musipelago_A_Really_Long_World_Name_123" in y
    assert "name: A_Really_Long_W" in y  # slot capped to 16 chars
    assert "StartingAlbum: album_001" in y
    assert "AllowPlayingAnyTrack: true" in y


def test_output_root_default_and_saved(tmp_path):
    import os

    app = _app_with_store(tmp_path)
    app.output_root = types.MethodType(g.MusipelagoAPWGenApp.output_root, app)
    assert app.output_root() == os.path.expanduser("~/Musipelago")  # default
    app._save_gen_setting("output_dir", "/tmp/worlds")
    assert app.output_root() == "/tmp/worlds"


# --- non-lossy track editing (ListContainer._apply_edit) -------------------


def _edit_container(album):
    stub = types.SimpleNamespace(apworld_data=[album], refreshed=0)
    stub.refresh_apworld_view = lambda: setattr(stub, "refreshed", stub.refreshed + 1)
    stub._apply_edit = types.MethodType(g.ListContainer._apply_edit, stub)
    return stub


def _full_album(n=3):
    a = _album("alb", n)
    a._all_tracks = list(a.tracks)  # what add_apworld_item stamps
    return a


def test_apply_edit_trims_then_readds_nonlossy(monkeypatch):
    monkeypatch.setattr(
        g,
        "App",
        types.SimpleNamespace(
            get_running_app=lambda: types.SimpleNamespace(
                root=types.SimpleNamespace(status_text="")
            )
        ),
    )
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
    monkeypatch.setattr(
        g,
        "App",
        types.SimpleNamespace(
            get_running_app=lambda: types.SimpleNamespace(
                root=types.SimpleNamespace(status_text="")
            )
        ),
    )
    album = _full_album(3)
    c = _edit_container(album)

    c._apply_edit(album, None)  # cancel
    assert len(album.tracks) == 3 and c.refreshed == 0

    c._apply_edit(album, [False, False, False])  # empty -> no-op (use Remove)
    assert len(album.tracks) == 3 and c.refreshed == 0
