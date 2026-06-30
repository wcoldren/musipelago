"""Pure tests for A3b album-pane art masking (album_art_for_display)."""

from musipelago.utils_client import KIVY_ICON, album_art_for_display

ART = "/covers/mixtape_03.jpg"


def test_shown_when_not_hidden():
    assert album_art_for_display(ART, hidden=False, all_finished=False) == ART


def test_masked_in_hidden_mode_until_finished():
    assert album_art_for_display(ART, hidden=True, all_finished=False) == KIVY_ICON


def test_unlocks_when_all_finished_even_in_hidden_mode():
    assert album_art_for_display(ART, hidden=True, all_finished=True) == ART


def test_finished_always_shows_real_art():
    assert album_art_for_display(ART, hidden=False, all_finished=True) == ART
