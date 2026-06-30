"""Pure tests for the stats panel core (compute_stats / format_hms / build_stats_rows / clamp)."""

import types

from musipelago.utils_client import (
    build_stats_rows,
    clamp_panel_width,
    compute_stats,
    format_hms,
)


def _track(uri, dur_ms):
    return types.SimpleNamespace(uri=uri, duration_ms=dur_ms)


def _album(tracks):
    return types.SimpleNamespace(tracks=tracks)


# --- format_hms ---
def test_format_hms_sub_hour():
    assert format_hms(3 * 60_000 + 5_000) == "03:05"


def test_format_hms_multi_hour():
    assert format_hms(2 * 3_600_000 + 14 * 60_000 + 9_000) == "2:14:09"


def test_format_hms_zero_and_negative():
    assert format_hms(0) == "00:00"
    assert format_hms(-5) == "00:00"
    assert format_hms("x") == "00:00"


# --- clamp_panel_width ---
def test_clamp_panel_width():
    assert clamp_panel_width(100, 240, 560) == 240
    assert clamp_panel_width(999, 240, 560) == 560
    assert clamp_panel_width(300, 240, 560) == 300
    assert clamp_panel_width("nope", 240, 560) == 240


# --- compute_stats ---
def _state():
    # 2 albums: A (owned) 2 tracks 60s each (1 finished), B (unowned) 1 track 120s (unfinished).
    cache = {
        "A": _album([_track("a1", 60_000), _track("a2", 60_000)]),
        "B": _album([_track("b1", 120_000)]),
    }
    prog = {
        "a1": {"is_finished": True, "parent_uri": "A", "hint_text": None},
        "a2": {"is_finished": False, "parent_uri": "A", "hint_text": "hint!"},
        "b1": {"is_finished": False, "parent_uri": "B", "hint_text": None},
    }
    return cache, prog


def _compute(**over):
    cache, prog = _state()
    base = dict(
        track_progress=prog,
        album_data_cache=cache,
        owned_albums={"A"},
        ordered_album_uris=["A", "B"],
        checked_locations={10},
        missing_locations={11, 12},
        received_items=[{"item": 5}, {"item": 9}],
        id_to_item_name={5: "Album finished!", 9: "Scratched disc"},
    )
    base.update(over)
    return compute_stats(**base)


def test_core_counts():
    s = _compute()
    assert (s["checks_found"], s["checks_total"], s["checks_pct"]) == (1, 3, 33)
    assert (s["albums_unlocked"], s["albums_total"]) == (1, 2)


def test_listening_time_join():
    s = _compute()
    assert s["ms_listened"] == 60_000  # a1
    assert s["ms_left"] == 60_000 + 120_000  # a2 + b1
    assert s["ms_total"] == 240_000
    assert s["ms_left_playable"] == 60_000  # a2 only (b1's album B unowned)


def test_ap_details():
    s = _compute()
    assert s["items_received"] == 2
    assert s["hints_active"] == 1  # a2
    assert s["albums_finished"] == 1  # one "Album finished!" received
    assert s["victory"] is False  # 1 < 2 albums


def test_victory_when_all_albums_finished():
    s = _compute(
        received_items=[{"item": 5}, {"item": 5}],
        id_to_item_name={5: "Album finished!"},
    )
    assert s["albums_finished"] == 2 and s["victory"] is True


def test_extras():
    s = _compute()
    assert s["track_count"] == 3
    assert s["track_longest_ms"] == 120_000
    assert s["track_shortest_ms"] == 60_000
    assert s["track_avg_ms"] == 80_000
    assert s["mixtapes_touched"] == 1  # only album A has a finished track


def test_current_album():
    s = _compute(current_album_uri="A")
    assert (s["current_album_finished"], s["current_album_total"]) == (1, 2)
    assert s["current_album_ms_left"] == 60_000


def test_empty_state_no_div_by_zero():
    s = compute_stats(
        track_progress={},
        album_data_cache={},
        owned_albums=set(),
        ordered_album_uris=[],
        checked_locations=set(),
        missing_locations=set(),
        received_items=[],
        id_to_item_name={},
    )
    assert s["checks_pct"] == 0 and s["track_avg_ms"] == 0 and s["victory"] is False


# --- build_stats_rows ---
def test_build_stats_rows_has_sections_and_values():
    rows = build_stats_rows(_compute(current_album_uri="A"))
    headers = [r["label"] for r in rows if r["kind"] == "header"]
    assert headers == ["Progress", "Listening", "Archipelago", "Extras"]
    flat = {r["label"]: r["value"] for r in rows if r["kind"] == "stat"}
    assert flat["Checks found"] == "1 / 3  (33%)"
    assert flat["Time left"] == "03:00"  # 180s
    assert flat["Library total"] == "04:00"
    assert "Current album" in flat


def test_current_album_row_absent_when_none():
    rows = build_stats_rows(_compute())  # no current_album_uri
    assert all(r["label"] != "Current album" for r in rows)
