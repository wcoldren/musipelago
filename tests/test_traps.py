"""Unit tests for the trap once-only dispatch cursor (``count_pending_traps``).

This is the heart of A1: a trap must fire EXACTLY ONCE per received instance and never
re-fire when the server replays the item backlog (reconnect) or the app restarts and rebuilds
``received_items`` from scratch. The pure function is tested here without importing the
VLC-backed client (mirrors the guess-matcher extraction)."""

import random

from musipelago.utils_client import (
    count_pending_traps,
    eligible_shuffle_tracks,
    pick_shuffle_tracks,
)

TRAP = "Bad Track Trap"
ID_MAP = {5: TRAP, 7: "[Bandit] [alb1]", 9: "Album finished!", 6: "Scratched disc"}
TRAP_NAMES = {TRAP}


def _items(*ids):
    """Build a received_items-style list of {'item': id} packets."""
    return [{"item": i} for i in ids]


def test_fresh_traps_fire():
    # Two trap instances received, none fired yet -> both pending.
    assert count_pending_traps(_items(5, 5), ID_MAP, TRAP_NAMES, 0) == 2


def test_reconnect_replays_nothing():
    # Server replays the full backlog; cursor already at 2 -> nothing re-fires.
    assert count_pending_traps(_items(5, 5), ID_MAP, TRAP_NAMES, 2) == 0


def test_restart_with_persisted_cursor():
    # App restart: received_items rebuilt from index 0, cursor loaded from store.
    received = _items(7, 5, 9, 5, 6)  # 2 traps among album/victory/junk items
    assert count_pending_traps(received, ID_MAP, TRAP_NAMES, 2) == 0


def test_partial_backlog_only_new_fire():
    # 3 traps seen, 1 already fired -> 2 new.
    assert count_pending_traps(_items(5, 5, 5), ID_MAP, TRAP_NAMES, 1) == 2


def test_non_trap_items_ignored():
    # Album unlocks, victory, and junk are not traps.
    assert count_pending_traps(_items(7, 9, 6, 7), ID_MAP, TRAP_NAMES, 0) == 0


def test_traps_disabled_no_names():
    # Empty trap_names (traps off / no slot_data) -> never fires, even with trap ids present.
    assert count_pending_traps(_items(5, 5), ID_MAP, set(), 0) == 0


def test_unknown_item_ids_ignored():
    # Ids missing from the data package resolve to None and are skipped.
    assert count_pending_traps(_items(999, 5, 999), ID_MAP, TRAP_NAMES, 0) == 1


def test_empty_inbox():
    assert count_pending_traps([], ID_MAP, TRAP_NAMES, 0) == 0


def test_cursor_ahead_never_negative():
    # Defensive: a stale cursor larger than seen must not return a negative delta.
    assert count_pending_traps(_items(5), ID_MAP, TRAP_NAMES, 5) == 0


# --- Shuffle Trap selection (the flagship effect picks from already-played, owned tracks) ---
def _prog(*entries):
    """Build a track_progress dict: each entry is (uri, is_finished, parent_uri)."""
    return {uri: {"is_finished": fin, "parent_uri": parent} for uri, fin, parent in entries}


def test_eligible_only_finished_and_owned():
    prog = _prog(
        ("t1", True, "albA"),  # finished + owned -> eligible
        ("t2", False, "albA"),  # not finished -> out
        ("t3", True, "albB"),  # finished but album not owned -> out
        ("t4", True, "albA"),  # finished + owned -> eligible
    )
    owned = {"albA"}
    assert set(eligible_shuffle_tracks(prog, owned)) == {"t1", "t4"}


def test_eligible_empty_when_nothing_finished():
    prog = _prog(("t1", False, "albA"), ("t2", False, "albA"))
    assert eligible_shuffle_tracks(prog, {"albA"}) == []


def test_pick_count_is_min_of_n_and_pool():
    pool = ["a", "b", "c"]
    assert len(pick_shuffle_tracks(pool, 2, random.Random(0))) == 2
    assert len(pick_shuffle_tracks(pool, 10, random.Random(0))) == 3  # capped at pool size


def test_pick_distinct_and_from_pool():
    pool = ["a", "b", "c", "d"]
    got = pick_shuffle_tracks(pool, 3, random.Random(1))
    assert len(got) == len(set(got)) == 3
    assert set(got) <= set(pool)


def test_pick_deterministic_under_seed():
    pool = ["a", "b", "c", "d", "e"]
    assert pick_shuffle_tracks(pool, 3, random.Random(42)) == pick_shuffle_tracks(
        pool, 3, random.Random(42)
    )


def test_pick_empty_or_nonpositive():
    assert pick_shuffle_tracks([], 3, random.Random(0)) == []
    assert pick_shuffle_tracks(["a", "b"], 0, random.Random(0)) == []
    assert pick_shuffle_tracks(["a", "b"], -1, random.Random(0)) == []
