"""Pure tests for the now-playing blue-highlight row flagging (mark_active_rows)."""

from musipelago.utils_client import mark_active_rows


def _rows(*uris):
    return [{"raw_uri": u, "is_playing_now": False} for u in uris]


def test_flags_only_the_matching_row():
    rows = _rows("a", "b", "c")
    changed = mark_active_rows(rows, "b")
    assert changed is True
    assert [r["is_playing_now"] for r in rows] == [False, True, False]


def test_clears_previous_and_moves_highlight():
    rows = _rows("a", "b", "c")
    mark_active_rows(rows, "b")
    mark_active_rows(rows, "c")  # move highlight b -> c
    assert [r["is_playing_now"] for r in rows] == [False, False, True]


def test_no_match_clears_all():
    rows = _rows("a", "b")
    rows[0]["is_playing_now"] = True
    changed = mark_active_rows(rows, "zzz")
    assert changed is True
    assert all(not r["is_playing_now"] for r in rows)


def test_falsy_uri_clears_all():
    rows = _rows("a", "b")
    rows[1]["is_playing_now"] = True
    assert mark_active_rows(rows, None) is True
    assert all(not r["is_playing_now"] for r in rows)


def test_idempotent_returns_false_when_unchanged():
    rows = _rows("a", "b")
    mark_active_rows(rows, "a")
    assert mark_active_rows(rows, "a") is False  # already correct -> no change


def test_missing_raw_uri_key_is_safe():
    rows = [{"is_playing_now": False}, {"raw_uri": "b", "is_playing_now": False}]
    assert mark_active_rows(rows, "b") is True
    assert rows[0]["is_playing_now"] is False
    assert rows[1]["is_playing_now"] is True
