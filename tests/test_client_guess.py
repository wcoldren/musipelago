"""Tests for the guess-mode title matcher (Feature A2a).

The matcher lives in ``utils_client`` (pure, no VLC/Kivy-window deps) so it runs in
CI without libvlc. It backs the per-row Guess button: a correct fuzzy guess awards the
track's AP check. The softlock-avoidance rule (Reveal = give up still releases the
check) lives in the client's ``complete_track`` path, not in the matcher — the matcher
only decides whether a *guess* counts.
"""
from musipelago.utils_client import _normalize_title, _titles_match


def test_exact_match():
    assert _titles_match("Paranoid Android", "Paranoid Android")


def test_case_insensitive():
    assert _titles_match("pArAnOiD aNdRoId", "Paranoid Android")


def test_ignores_punctuation():
    assert _titles_match("dont stop me now!!!", "Don't Stop, Me Now")


def test_ignores_remaster_and_bracket_tags():
    assert _titles_match("Karma Police", "Karma Police (Remastered 2017)")
    assert _titles_match("Bittersweet Symphony", "Bittersweet Symphony [Radio Edit]")


def test_fuzzy_typo_within_threshold():
    # one-letter typo -> ratio stays >= 0.85
    assert _titles_match("Bohemian Rhapsdy", "Bohemian Rhapsody")


def test_clearly_wrong_guess_rejected():
    assert not _titles_match("Yellow Submarine", "Paranoid Android")


def test_empty_guess_never_matches():
    assert not _titles_match("", "Paranoid Android")
    assert not _titles_match("   ", "Paranoid Android")
    # a title that normalizes to empty (only punctuation) also can't match
    assert not _titles_match("!!!", "!!!")


def test_normalize_strips_tags_and_punctuation():
    # apostrophes (like all punctuation) become spaces, so "don't" -> "don t";
    # the fuzzy ratio in _titles_match is what absorbs that for real guesses.
    assert _normalize_title("Don't Stop! (Live, 1999)") == "don t stop"
    assert _normalize_title("  Multiple   Spaces  ") == "multiple spaces"
    assert _normalize_title(None) == ""
