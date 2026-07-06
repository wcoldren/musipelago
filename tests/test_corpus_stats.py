"""Pure tests for the gen-app corpus stats helpers (corpus_stats / pack_layout_summary
/ format_hm). No Kivy — SimpleNamespace track/album fixtures, direct import."""

import types

from musipelago.utils import corpus_stats, format_hm, pack_layout_summary


def _track(dur_ms):
    return types.SimpleNamespace(duration_ms=dur_ms)


def _album(*durs):
    return types.SimpleNamespace(tracks=[_track(d) for d in durs])


# --- corpus_stats ---------------------------------------------------------------


def test_corpus_stats_empty():
    s = corpus_stats([])
    assert s == {
        "n_albums": 0,
        "n_tracks": 0,
        "total_ms": 0,
        "mean_ms": 0,
        "median_ms": 0,
        "min_ms": 0,
        "max_ms": 0,
        "n_unknown": 0,
    }


def test_corpus_stats_all_unknown():
    # duration_ms falsy (None/0): counted as tracks + unknown, excluded from duration stats.
    s = corpus_stats([_album(0, None), _album(0)])
    assert s["n_albums"] == 2
    assert s["n_tracks"] == 3
    assert s["n_unknown"] == 3
    assert s["total_ms"] == s["mean_ms"] == s["median_ms"] == s["min_ms"] == s["max_ms"] == 0


def test_corpus_stats_single_track():
    s = corpus_stats([_album(204_000)])
    assert s["n_albums"] == 1
    assert s["n_tracks"] == 1
    assert s["n_unknown"] == 0
    assert s["total_ms"] == 204_000
    assert s["mean_ms"] == s["median_ms"] == s["min_ms"] == s["max_ms"] == 204_000


def test_corpus_stats_mixed_known_unknown():
    # known: [60_000, 120_000]; one unknown (0) excluded from duration stats.
    s = corpus_stats([_album(60_000, 0), _album(120_000)])
    assert s["n_tracks"] == 3
    assert s["n_unknown"] == 1
    assert s["total_ms"] == 180_000
    assert s["mean_ms"] == 90_000
    assert s["median_ms"] == 90_000
    assert s["min_ms"] == 60_000
    assert s["max_ms"] == 120_000


def test_corpus_stats_median_odd():
    s = corpus_stats([_album(30_000, 60_000, 90_000)])
    assert s["median_ms"] == 60_000


def test_corpus_stats_median_even():
    # even count -> average of the two middle values (60_000 and 90_000).
    s = corpus_stats([_album(30_000, 60_000, 90_000, 120_000)])
    assert s["median_ms"] == 75_000


# --- pack_layout_summary --------------------------------------------------------


def test_pack_layout_empty():
    s = pack_layout_summary([])
    assert s == {"n_packs": 0, "n_tracks": 0, "min_min": 0, "median_min": 0, "max_min": 0}


def test_pack_layout_single_pack():
    # one pack of two 3-min tracks -> 6 minutes.
    s = pack_layout_summary([_album(180_000, 180_000)])
    assert s == {"n_packs": 1, "n_tracks": 2, "min_min": 6, "median_min": 6, "max_min": 6}


def test_pack_layout_several_packs():
    # per-pack minutes: 20, 24, 26 (floored) -> min 20, median 24, max 26.
    s = pack_layout_summary(
        [
            _album(20 * 60_000),
            _album(24 * 60_000),
            _album(26 * 60_000),
        ]
    )
    assert s["n_packs"] == 3
    assert s["n_tracks"] == 3
    assert (s["min_min"], s["median_min"], s["max_min"]) == (20, 24, 26)


def test_pack_layout_unknown_durations_count_as_zero_minutes():
    # a pack whose tracks all lack duration contributes 0 minutes but still counts tracks.
    s = pack_layout_summary([_album(0, None), _album(24 * 60_000)])
    assert s["n_packs"] == 2
    assert s["n_tracks"] == 3
    assert s["min_min"] == 0
    assert s["max_min"] == 24


# --- format_hm ------------------------------------------------------------------


def test_format_hm_boundaries():
    assert format_hm(0) == "0m"
    assert format_hm(52 * 60_000) == "52m"
    assert format_hm((3 * 60 + 52) * 60_000) == "3h 52m"
    assert format_hm(60 * 60_000) == "1h 0m"
    assert format_hm(59_999) == "0m"  # rounds down to the minute


def test_format_hm_bad_input():
    assert format_hm(-1) == "0m"
    assert format_hm(None) == "0m"
    assert format_hm("nope") == "0m"
