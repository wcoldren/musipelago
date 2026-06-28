"""Unit tests for the trap once-only dispatch cursor (``count_pending_traps``).

This is the heart of A1: a trap must fire EXACTLY ONCE per received instance and never
re-fire when the server replays the item backlog (reconnect) or the app restarts and rebuilds
``received_items`` from scratch. The pure function is tested here without importing the
VLC-backed client (mirrors the guess-matcher extraction)."""

from musipelago.utils_client import count_pending_traps

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
