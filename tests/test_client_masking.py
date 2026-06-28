"""Tests for hidden-mode row masking + reveal (A3 / B3-pivot).

In hidden ("unknown song") and guess (A2a) mode a track row is built with its title,
artist, AP-location line, AND cover art replaced by placeholders, with the real values
stashed under ``raw_*`` keys. ``unmask_row`` restores them on finish / Reveal. It lives in
``utils_client`` (pure dict transform, no Kivy/VLC) so it runs in CI without libvlc — the
client's ``RootLayout._unmask_track_row`` just delegates to it.

The B3 pivot added the cover-art dimension: the album cover would otherwise give the answer
away, so it's masked alongside title/artist and revealed through the same chokepoint.
"""
from musipelago.utils_client import unmask_row, KIVY_ICON


def _masked_row(real_art):
    """A row dict as populate_track_list builds it for a hidden, not-yet-finished track."""
    return {
        'text_line_1': 'Unknown Track',
        'text_line_3': '???',
        'text_line_4': 'Unknown Artist',
        'image_source': KIVY_ICON,
        'raw_title': 'Paranoid Android',
        'raw_artist': 'Radiohead',
        'raw_line3': 'OK Computer - Slot 1',
        'raw_image_source': real_art,
    }


def test_unmask_restores_all_fields_including_art():
    art = '/cache/cover_abc.jpg'
    row = _masked_row(art)
    unmask_row(row)
    assert row['text_line_1'] == 'Paranoid Android'
    assert row['text_line_4'] == 'Radiohead'
    assert row['text_line_3'] == 'OK Computer - Slot 1'
    # the cover art is revealed too (the B3-pivot fix)
    assert row['image_source'] == art


def test_unmask_art_is_idempotent():
    art = 'https://example.test/rest/getCoverArt?id=7'
    row = _masked_row(art)
    unmask_row(row)
    unmask_row(row)
    assert row['image_source'] == art


def test_masked_row_hides_the_cover_before_reveal():
    # Sanity: while masked, the cover is the generic fallback, not the real art.
    row = _masked_row('/cache/cover_abc.jpg')
    assert row['image_source'] == KIVY_ICON
    assert row['image_source'] != row['raw_image_source']


def test_unmask_leaves_image_untouched_when_no_raw_stored():
    # A non-hidden row carries no raw_image_source; unmask must not clobber its art.
    row = {'text_line_1': 'Song', 'text_line_4': 'Artist', 'image_source': '/cache/real.jpg'}
    unmask_row(row)
    assert row['image_source'] == '/cache/real.jpg'


def test_unmask_tolerates_missing_raw_text_keys():
    # Defensive: a row missing raw_title/raw_artist keeps its current text, no KeyError.
    row = {'text_line_1': 'Keep', 'text_line_4': 'Me', 'image_source': KIVY_ICON}
    unmask_row(row)
    assert row['text_line_1'] == 'Keep'
    assert row['text_line_4'] == 'Me'
