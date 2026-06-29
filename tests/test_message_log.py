"""Tests for the message log / chat console helpers (B4).

The feed's core logic lives in ``utils_client`` (pure, no VLC/Kivy-window deps) so it
runs in CI without libvlc. ``compose_printjson_text`` turns an AP ``PrintJSON`` packet's
``data`` parts into one plain display string (for the status bar); ``printjson_markup``
builds the AP-colored Kivy markup for the feed; ``make_log_entry`` / ``append_capped``
back the bounded scrolling feed.
"""

from musipelago.utils_client import (
    AP_COLOR_CODES,
    append_capped,
    compose_printjson_text,
    make_log_entry,
    printjson_markup,
)


def _resolve(part_type, text, part):
    """Stand-in for the client's id->name resolver."""
    if part_type == "player_id":
        return f"Player{text}"
    if part_type == "item_id":
        return f"Item{text}"
    if part_type == "location_id":
        return f"Loc{text}"
    return text


# --- compose_printjson_text ---
def test_plain_text_parts_concatenate():
    parts = [{"text": "hello "}, {"text": "world"}]
    assert compose_printjson_text(parts, _resolve) == "hello world"


def test_typed_parts_resolved():
    parts = [
        {"type": "player_id", "text": "1"},
        {"text": " found "},
        {"type": "item_id", "text": "42", "player": 1},
        {"text": " at "},
        {"type": "location_id", "text": "7", "player": 2},
    ]
    assert compose_printjson_text(parts, _resolve) == "Player1 found Item42 at Loc7"


def test_resolver_exception_falls_back_to_raw_text():
    def boom(part_type, text, part):
        raise ValueError("no data package yet")

    parts = [{"type": "item_id", "text": "42", "player": 1}]
    # On any resolver failure we keep the raw text rather than dropping the message.
    assert compose_printjson_text(parts, boom) == "42"


def test_non_dict_parts_skipped():
    parts = ["not a dict", {"text": "ok"}, 5]
    assert compose_printjson_text(parts, _resolve) == "ok"


def test_empty_parts_give_empty_string():
    assert compose_printjson_text([], _resolve) == ""


# --- printjson_markup (AP per-part coloring) ---
def test_markup_plain_text_is_uncolored():
    parts = [{"text": "hello world"}]
    assert printjson_markup(parts, _resolve) == "hello world"


def test_markup_item_colored_by_flags():
    prog = AP_COLOR_CODES["plum"]
    useful = AP_COLOR_CODES["slateblue"]
    trap = AP_COLOR_CODES["salmon"]
    filler = AP_COLOR_CODES["cyan"]
    assert (
        printjson_markup([{"type": "item_id", "text": "1", "player": 1, "flags": 1}], _resolve)
        == f"[color={prog}]Item1[/color]"
    )
    assert (
        printjson_markup([{"type": "item_id", "text": "2", "player": 1, "flags": 2}], _resolve)
        == f"[color={useful}]Item2[/color]"
    )
    assert (
        printjson_markup([{"type": "item_id", "text": "3", "player": 1, "flags": 4}], _resolve)
        == f"[color={trap}]Item3[/color]"
    )
    assert (
        printjson_markup([{"type": "item_id", "text": "4", "player": 1, "flags": 0}], _resolve)
        == f"[color={filler}]Item4[/color]"
    )


def test_markup_player_self_vs_other():
    me = AP_COLOR_CODES["magenta"]
    other = AP_COLOR_CODES["yellow"]
    parts = [{"type": "player_id", "text": "1"}]
    assert printjson_markup(parts, _resolve, self_slot=1) == f"[color={me}]Player1[/color]"
    assert printjson_markup(parts, _resolve, self_slot=2) == f"[color={other}]Player1[/color]"


def test_markup_location_is_green():
    green = AP_COLOR_CODES["green"]
    parts = [{"type": "location_id", "text": "7", "player": 1}]
    assert printjson_markup(parts, _resolve) == f"[color={green}]Loc7[/color]"


def test_markup_escapes_brackets_in_names():
    # Item names with literal brackets must not be parsed as markup tags.
    def resolve(part_type, text, part):
        return "[Radio Edit]"

    out = printjson_markup([{"type": "item_id", "text": "1", "player": 1, "flags": 0}], resolve)
    assert "&bl;Radio Edit&br;" in out
    assert "[Radio Edit]" not in out


# --- make_log_entry ---
def test_make_log_entry_shape():
    assert make_log_entry("hi") == {"text": "hi"}


# --- append_capped ---
def test_append_capped_appends_in_place():
    entries = []
    ret = append_capped(entries, make_log_entry("one"), cap=10)
    assert ret is entries
    assert entries == [{"text": "one"}]


def test_append_capped_trims_oldest_keeping_newest():
    entries = []
    for i in range(250):
        append_capped(entries, make_log_entry(str(i)), cap=200)
    assert len(entries) == 200
    # oldest dropped, newest kept
    assert entries[0]["text"] == "50"
    assert entries[-1]["text"] == "249"
