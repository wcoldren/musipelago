"""Unit tests for ``build_meta_albums`` (Feature 2 — randomized meta-albums).

A pure function of ``apworld_data``: it partitions the curated tracks across N
synthetic "Mixtape" packs while preserving real track URIs for playback. No Kivy
widgets are instantiated here.
"""

from collections import Counter

import musipelago.musipelago_apworld_gen as g
from musipelago.backends import GenericAlbum, GenericTrack


def track(uri, title, artist):
    return GenericTrack(
        uri=uri, title=title, artist=artist, album_title="orig", duration_ms=1000, service="local"
    )


def album(uri, n, artist="A", title_prefix="t"):
    tracks = [track(f"{uri}/{i}", f"{title_prefix}{i}", artist) for i in range(n)]
    return GenericAlbum(
        uri=uri,
        title=uri,
        artist=artist,
        image_url="",
        total_tracks=n,
        album_type="Album",
        service="local",
        tracks=tracks,
    )


def all_uris(albums):
    return Counter(t.uri for a in albums for t in a.tracks)


# 5 + 7 + 3 = 15 tracks
SRC = [album("alb1", 5), album("alb2", 7), album("alb3", 3)]
SRC_URIS = all_uris(SRC)
TOTAL = sum(SRC_URIS.values())


def assert_partition(metas):
    """Every source track appears exactly once across the metas, with consistent
    per-meta bookkeeping and unique album identity keys/URIs."""
    assert all_uris(metas) == SRC_URIS
    for m in metas:
        assert m.total_tracks == len(m.tracks)
        assert m.artist == "Musipelago"
        assert m.uri.startswith("meta:")
    keys = [f"[{m.artist}] [{m.title}]" for m in metas]
    assert len(keys) == len(set(keys)), ("dup album keys", keys)
    uris = [m.uri for m in metas]
    assert len(uris) == len(set(uris)), ("dup album uris", uris)


def test_total_fixture_sanity():
    assert TOTAL == 15


def test_packs_mode_makes_n_nearequal_groups():
    metas = g.build_meta_albums(SRC, mode="packs", count=4, seed=1)
    assert len(metas) == 4
    assert_partition(metas)
    sizes = sorted(len(m.tracks) for m in metas)
    assert sizes == [3, 4, 4, 4]  # 15 into 4 -> 4,4,4,3
    assert all(len(m.tracks) > 0 for m in metas)


def test_per_pack_mode_groups_of_count():
    metas = g.build_meta_albums(SRC, mode="per_pack", count=4, seed=1)
    assert [len(m.tracks) for m in metas].count(4) >= 3  # 4,4,4,3
    assert sum(len(m.tracks) for m in metas) == TOTAL
    assert_partition(metas)


def test_seed_is_reproducible_and_varies():
    def layout(metas):
        return [sorted(t.uri for t in m.tracks) for m in metas]

    a = g.build_meta_albums(SRC, mode="packs", count=4, seed=42)
    b = g.build_meta_albums(SRC, mode="packs", count=4, seed=42)
    assert layout(a) == layout(b), "same seed should reproduce"
    c = g.build_meta_albums(SRC, mode="packs", count=4, seed=999)
    assert layout(a) != layout(c), "different seed should differ"


def test_title_collision_guard_and_no_source_mutation():
    # 6 tracks with identical title+artist forced into one pack.
    dup = [album("dupA", 0)]
    dup[0].tracks = [track(f"i{i}", "Intro", "Band") for i in range(6)]
    dup[0].total_tracks = 6
    metas = g.build_meta_albums(dup, mode="packs", count=1, seed=0)
    assert len(metas) == 1
    m = metas[0]
    loc_names = [f"[{t.artist}] [{m.title}] [{t.title}]" for t in m.tracks]
    assert len(loc_names) == len(set(loc_names)), ("collision!", loc_names)
    # real URIs preserved despite retitling
    assert sorted(t.uri for t in m.tracks) == [f"i{i}" for i in range(6)]
    # source tracks NOT mutated (titles still "Intro")
    assert all(t.title == "Intro" for t in dup[0].tracks), "source mutated!"


def test_count_greater_than_tracks_has_no_empty_packs():
    metas = g.build_meta_albums([album("small", 3)], mode="packs", count=10, seed=0)
    assert len(metas) == 3
    assert all(len(m.tracks) == 1 for m in metas)


def test_empty_input_returns_unchanged():
    assert g.build_meta_albums([], mode="packs", count=4) == []


# --- A5: randomizer controls (subset, shuffle, minutes mode) --------------


def flat_uris(albums):
    """Track URIs in source order (no Counter), for order-sensitive asserts."""
    return [t.uri for a in albums for t in a.tracks]


def test_subset_truncates_track_pool():
    metas = g.build_meta_albums(SRC, mode="packs", count=4, seed=1, subset=8)
    assert sum(len(m.tracks) for m in metas) == 8
    uris = [t.uri for m in metas for t in m.tracks]
    assert len(uris) == len(set(uris)) == 8  # no dups, kept tracks unique
    assert set(uris) <= set(SRC_URIS)  # all came from the source pool


def test_subset_none_zero_or_oversized_keeps_all():
    for sub in (None, 0, TOTAL, TOTAL + 100):
        metas = g.build_meta_albums(SRC, mode="packs", count=4, seed=1, subset=sub)
        assert all_uris(metas) == SRC_URIS, sub


def test_shuffle_false_preserves_catalog_order():
    metas = g.build_meta_albums(SRC, mode="per_pack", count=4, shuffle=False)
    assert flat_uris(metas) == flat_uris(SRC)
    assert_partition(metas)


def test_shuffle_false_with_subset_takes_first_k():
    metas = g.build_meta_albums(SRC, mode="per_pack", count=100, shuffle=False, subset=5)
    assert flat_uris(metas) == flat_uris(SRC)[:5]


def test_subset_reproducible_with_seed():
    chosen = lambda m: sorted(t.uri for a in m for t in a.tracks)
    a = g.build_meta_albums(SRC, mode="packs", count=3, seed=42, subset=10)
    b = g.build_meta_albums(SRC, mode="packs", count=3, seed=42, subset=10)
    assert chosen(a) == chosen(b)  # same seed+subset -> same picks
    c = g.build_meta_albums(SRC, mode="packs", count=3, seed=999, subset=10)
    assert chosen(a) != chosen(c)  # different seed -> different picks


def _timed_album(uri, n, dur_ms):
    tracks = [
        GenericTrack(
            uri=f"{uri}/{i}",
            title=f"t{i}",
            artist="A",
            album_title="orig",
            duration_ms=dur_ms,
            service="local",
        )
        for i in range(n)
    ]
    return GenericAlbum(
        uri=uri,
        title=uri,
        artist="A",
        image_url="",
        total_tracks=n,
        album_type="Album",
        service="local",
        tracks=tracks,
    )


def test_minutes_mode_packs_to_target_duration():
    # 12 tracks of 3 minutes; target 9 min -> packs of ~3 tracks.
    src = [_timed_album("timed", 12, 3 * 60 * 1000)]
    metas = g.build_meta_albums(src, mode="minutes", count=9, shuffle=False)
    assert sum(len(m.tracks) for m in metas) == 12  # nothing dropped
    full = [m for m in metas if len(m.tracks) == 3]
    assert len(full) >= 3  # most packs hit the target
    # each full pack is exactly the 9-minute target
    assert all(sum(t.duration_ms for t in m.tracks) == 9 * 60 * 1000 for m in full)
    uris = [t.uri for m in metas for t in m.tracks]
    assert len(uris) == len(set(uris)) == 12  # partition invariant


def test_minutes_mode_zero_duration_falls_back_to_single_pack():
    src = [_timed_album("nodur", 5, 0)]
    metas = g.build_meta_albums(src, mode="minutes", count=10)
    assert sum(len(m.tracks) for m in metas) == 5  # no crash, nothing lost


# --- Balanced grid mode (A5b): exact N packs x M songs, duration-balanced ---
def _varied_album(uri, durations):
    """An album whose track i has duration durations[i] (ms)."""
    tracks = [
        GenericTrack(
            uri=f"{uri}/{i}",
            title=f"t{i}",
            artist="A",
            album_title="orig",
            duration_ms=d,
            service="local",
        )
        for i, d in enumerate(durations)
    ]
    return GenericAlbum(
        uri=uri,
        title=uri,
        artist="A",
        image_url="",
        total_tracks=len(tracks),
        album_type="Album",
        service="local",
        tracks=tracks,
    )


def _pack_sums(metas):
    return [sum(t.duration_ms for t in m.tracks) for m in metas]


def _grid_partition_ok(metas, expect_packs, expect_size):
    assert len(metas) == expect_packs
    assert all(len(m.tracks) == expect_size for m in metas)
    uris = [t.uri for m in metas for t in m.tracks]
    assert len(uris) == len(set(uris))  # no track duplicated across packs
    keys = [m.uri for m in metas]
    assert len(keys) == len(set(keys))  # unique meta identities


def test_grid_mode_exact_10x5():
    src = [_timed_album("g", 50, 4 * 60 * 1000)]  # exactly 50 tracks
    metas = g.build_meta_albums(src, mode="grid", count=10, pack_size=5, seed=1)
    _grid_partition_ok(metas, expect_packs=10, expect_size=5)


def test_grid_balances_better_than_sequential_split():
    # Highly variable durations (1..50 minutes) -> a naive consecutive split is
    # lumpy; the LPT grid packer should produce a much tighter per-pack spread.
    durations = [(i + 1) * 60 * 1000 for i in range(50)]
    src = [_varied_album("v", durations)]
    grid = g.build_meta_albums(src, mode="grid", count=10, pack_size=5, seed=7)
    seq = g.build_meta_albums(src, mode="per_pack", count=5, seed=7)  # same seeded shuffle
    grid_spread = max(_pack_sums(grid)) - min(_pack_sums(grid))
    seq_spread = max(_pack_sums(seq)) - min(_pack_sums(seq))
    assert grid_spread < seq_spread
    _grid_partition_ok(grid, expect_packs=10, expect_size=5)


def test_grid_soft_target_uniform_hits_target():
    # 50 tracks x 4 min, 5 per pack, target 20 -> every pack lands exactly on 20 min.
    src = [_timed_album("g", 50, 4 * 60 * 1000)]
    metas = g.build_meta_albums(src, mode="grid", count=10, pack_size=5, target_minutes=20, seed=2)
    assert all(s == 20 * 60 * 1000 for s in _pack_sums(metas))


def test_grid_pool_smaller_keeps_size_fewer_packs():
    src = [_timed_album("g", 23, 60 * 1000)]  # 23 < 10*5
    metas = g.build_meta_albums(src, mode="grid", count=10, pack_size=5, seed=1)
    assert len(metas) == 5  # ceil(23/5)
    assert all(len(m.tracks) <= 5 for m in metas)
    assert sum(len(m.tracks) for m in metas) == 23  # nothing lost, none empty
    assert all(len(m.tracks) > 0 for m in metas)


def test_grid_pool_larger_drops_extras():
    src = [_timed_album("g", 60, 60 * 1000)]  # 60 > 10*5
    metas = g.build_meta_albums(src, mode="grid", count=10, pack_size=5, seed=1)
    _grid_partition_ok(metas, expect_packs=10, expect_size=5)  # exactly 50 used, 10 dropped


def test_grid_ignores_subset():
    src = [_timed_album("g", 60, 60 * 1000)]
    metas = g.build_meta_albums(src, mode="grid", count=10, pack_size=5, subset=12, seed=1)
    assert sum(len(m.tracks) for m in metas) == 50  # subset=12 ignored; N*M wins


def test_grid_seed_reproducible():
    src = [_timed_album("g", 60, 60 * 1000)]
    a = g.build_meta_albums(src, mode="grid", count=10, pack_size=5, seed=42)
    b = g.build_meta_albums(src, mode="grid", count=10, pack_size=5, seed=42)
    c = g.build_meta_albums(src, mode="grid", count=10, pack_size=5, seed=99)

    def layout(metas):
        return [sorted(t.uri for t in m.tracks) for m in metas]

    assert layout(a) == layout(b)  # same seed -> identical
    assert layout(a) != layout(c)  # different seed -> different draw/layout


def test_grid_empty_pool_returns_source():
    assert g.build_meta_albums([], mode="grid", count=10, pack_size=5) == []


# --- Track origin: mixtape tracks retain their source album name + cover ---
def _art_album(uri, n, image_url):
    a = album(uri, n)
    return GenericAlbum(
        uri=a.uri,
        title=a.title,
        artist=a.artist,
        image_url=image_url,
        total_tracks=n,
        album_type="Album",
        service="local",
        tracks=a.tracks,
    )


def test_mixtape_tracks_keep_source_album_and_art():
    src = [_art_album("alb1", 2, "/covers/alb1.jpg"), _art_album("alb2", 3, "/covers/alb2.jpg")]
    origin = {t.uri: (al.title, al.image_url) for al in src for t in al.tracks}
    metas = g.build_meta_albums(src, mode="packs", count=1, seed=1)  # one mixtape, all tracks
    assert len(metas) == 1
    for t in metas[0].tracks:
        exp_album, exp_art = origin[t.uri]
        assert t.source_album == exp_album  # remembers the real album
        assert t.source_image_url == exp_art  # remembers the real cover
        assert t.album_title == "Mixtape 01"  # display grouping is the mixtape
        assert t.artist == "A"  # real artist preserved
