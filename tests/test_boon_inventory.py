"""Pure tests for the spendable boon inventory (tally_by_name / boon_target_ok / held math)."""

from musipelago.utils_client import boon_target_ok, tally_by_name


def _items(*ids):
    return [{"item": i} for i in ids]


ID_MAP = {
    5: "Reveal Token",
    6: "Skip Token",
    7: "Shuffle Trap",
    9: "Album finished!",
}
BOON_NAMES = {"Reveal Token", "Skip Token"}
TRAP_NAMES = {"Shuffle Trap", "Bad Track Trap", "Seek Trap"}


# --- tally_by_name ---
def test_tally_buckets_by_name():
    got = tally_by_name(_items(5, 6, 5, 9, 7), ID_MAP, BOON_NAMES)
    assert got == {"Reveal Token": 2, "Skip Token": 1}  # ignores trap/victory items


def test_tally_traps():
    assert tally_by_name(_items(7, 7, 5), ID_MAP, TRAP_NAMES) == {"Shuffle Trap": 2}


def test_tally_empty():
    assert tally_by_name([], ID_MAP, BOON_NAMES) == {}
    assert tally_by_name(_items(5), ID_MAP, set()) == {}


# --- held = received - spent (the inventory math used in _dispatch_pending_boons) ---
def test_held_math():
    received = tally_by_name(_items(5, 5, 6), ID_MAP, BOON_NAMES)  # Reveal 2, Skip 1
    spent = {"Reveal Token": 1}
    held = {n: max(0, received.get(n, 0) - spent.get(n, 0)) for n in BOON_NAMES}
    assert held == {"Reveal Token": 1, "Skip Token": 1}


def test_held_never_negative():
    received = {"Skip Token": 1}
    spent = {"Skip Token": 3}  # over-spent (shouldn't happen) -> clamp 0
    held = {n: max(0, received.get(n, 0) - spent.get(n, 0)) for n in BOON_NAMES}
    assert held["Skip Token"] == 0


# --- boon_target_ok ---
def test_skip_needs_unfinished():
    assert boon_target_ok("Skip Token", is_finished=False, can_reveal=False) is True
    assert boon_target_ok("Skip Token", is_finished=True, can_reveal=False) is False


def test_reveal_needs_masked_row():
    assert boon_target_ok("Reveal Token", is_finished=False, can_reveal=True) is True
    assert boon_target_ok("Reveal Token", is_finished=False, can_reveal=False) is False


def test_unknown_boon_rejected():
    assert boon_target_ok("Mystery Token", is_finished=False, can_reveal=True) is False
