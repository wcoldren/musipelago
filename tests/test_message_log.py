"""Tests for the message log / chat console helpers (B4).

The feed's core logic lives in ``utils_client`` (pure, no VLC/Kivy-window deps) so it
runs in CI without libvlc. ``compose_printjson_text`` turns an AP ``PrintJSON`` packet's
``data`` parts into one display string (the same logic that previously lived inline in
the client's PrintJSON handler); ``make_log_entry`` / ``append_capped`` back the bounded
scrolling feed.
"""

from musipelago.utils_client import (
    append_capped,
    compose_printjson_text,
    make_log_entry,
    printjson_kind,
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


# --- printjson_kind ---
def test_printjson_kind_maps_known_types():
    assert printjson_kind("ItemSend") == "item"
    assert printjson_kind("Hint") == "hint"
    assert printjson_kind("Chat") == "chat"
    assert printjson_kind("ServerChat") == "chat"
    assert printjson_kind("Join") == "join"
    assert printjson_kind("Goal") == "goal"


def test_printjson_kind_defaults_to_server():
    assert printjson_kind(None) == "server"
    assert printjson_kind("SomeUnknownType") == "server"


# --- make_log_entry ---
def test_make_log_entry_defaults_to_server_kind():
    assert make_log_entry("hi") == {"text": "hi", "kind": "server"}


def test_make_log_entry_keeps_kind():
    assert make_log_entry("a hint", "hint") == {"text": "a hint", "kind": "hint"}


# --- append_capped ---
def test_append_capped_appends_in_place():
    entries = []
    ret = append_capped(entries, make_log_entry("one"), cap=10)
    assert ret is entries
    assert entries == [{"text": "one", "kind": "server"}]


def test_append_capped_trims_oldest_keeping_newest():
    entries = []
    for i in range(250):
        append_capped(entries, make_log_entry(str(i)), cap=200)
    assert len(entries) == 200
    # oldest dropped, newest kept
    assert entries[0]["text"] == "50"
    assert entries[-1]["text"] == "249"
