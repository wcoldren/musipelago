"""Unit tests for ``build_meta_albums`` (Feature 2 — randomized meta-albums).

A pure function of ``apworld_data``: it partitions the curated tracks across N
synthetic "Mixtape" packs while preserving real track URIs for playback. No Kivy
widgets are instantiated here.
"""
from collections import Counter

import musipelago.musipelago_apworld_gen as g
from musipelago.backends import GenericAlbum, GenericTrack


def track(uri, title, artist):
    return GenericTrack(uri=uri, title=title, artist=artist,
                        album_title="orig", duration_ms=1000, service="local")


def album(uri, n, artist="A", title_prefix="t"):
    tracks = [track(f"{uri}/{i}", f"{title_prefix}{i}", artist) for i in range(n)]
    return GenericAlbum(uri=uri, title=uri, artist=artist, image_url="",
                        total_tracks=n, album_type="Album", service="local",
                        tracks=tracks)


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
    assert sizes == [3, 4, 4, 4]            # 15 into 4 -> 4,4,4,3
    assert all(len(m.tracks) > 0 for m in metas)


def test_per_pack_mode_groups_of_count():
    metas = g.build_meta_albums(SRC, mode="per_pack", count=4, seed=1)
    assert [len(m.tracks) for m in metas].count(4) >= 3    # 4,4,4,3
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
