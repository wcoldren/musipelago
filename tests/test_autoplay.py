"""Pure tests for cross-album auto-advance (first_unfinished_track / next_album_start)."""

import types

from musipelago.utils_client import first_unfinished_track, next_album_start


def _track(uri):
    return types.SimpleNamespace(uri=uri)


def _album(uris):
    return types.SimpleNamespace(tracks=[_track(u) for u in uris])


def _prog(*finished_uris):
    # every uri seen across the test fixture; mark the given ones finished.
    all_uris = ["A1", "A2", "B1", "B2", "C1"]
    return {u: {"is_finished": u in finished_uris} for u in all_uris}


CACHE = {"A": _album(["A1", "A2"]), "B": _album(["B1", "B2"]), "C": _album(["C1"])}
ORDER = ["A", "B", "C"]


# --- first_unfinished_track ---
def test_first_unfinished():
    assert first_unfinished_track(CACHE["A"], _prog("A1")) == "A2"
    assert first_unfinished_track(CACHE["A"], _prog()) == "A1"
    assert first_unfinished_track(CACHE["A"], _prog("A1", "A2")) is None


# --- next_album_start ---
def test_next_owned_unfinished_in_order():
    # Just finished album A (both tracks done). Next owned-unfinished is B -> B1.
    owned = {"A", "B", "C"}
    assert next_album_start(ORDER, "A", owned, CACHE, _prog("A1", "A2")) == ("B", "B1")


def test_skips_unowned_albums():
    # B unowned -> skip to C.
    owned = {"A", "C"}
    assert next_album_start(ORDER, "A", owned, CACHE, _prog("A1", "A2")) == ("C", "C1")


def test_skips_fully_finished_albums():
    # B fully finished -> skip to C.
    owned = {"A", "B", "C"}
    prog = _prog("A1", "A2", "B1", "B2")
    assert next_album_start(ORDER, "A", owned, CACHE, prog) == ("C", "C1")


def test_wraps_past_end():
    # Finished C (last in order); A still has unfinished -> wrap to A.
    owned = {"A", "B", "C"}
    prog = _prog("C1")  # A/B unfinished
    assert next_album_start(ORDER, "C", owned, CACHE, prog) == ("A", "A1")


def test_none_when_everything_finished():
    owned = {"A", "B", "C"}
    prog = _prog("A1", "A2", "B1", "B2", "C1")
    assert next_album_start(ORDER, "A", owned, CACHE, prog) is None


def test_current_not_found_scans_from_top():
    owned = {"A", "B", "C"}
    assert next_album_start(ORDER, "ZZZ", owned, CACHE, _prog()) == ("A", "A1")


def test_empty_order():
    assert next_album_start([], "A", {"A"}, CACHE, _prog()) is None
