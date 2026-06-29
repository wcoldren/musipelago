"""End-to-end render test: feed meta-albums through the real Jinja templates and
verify the generated AP world files have no duplicate location/item names, compile as
valid Python, and agree on the victory count. Mirrors what
``GeneratePopup.generate_files`` does at generate time — this is the strongest guard on
the ``apworld_data`` -> template contract.
"""

import os
import py_compile
import re

import pytest
from jinja2 import Environment, FileSystemLoader

import musipelago.musipelago_apworld_gen as g
from musipelago.backends import GenericAlbum, GenericTrack
from musipelago.utils import filter_py_json, filter_to_ascii

TPL = os.path.join(os.path.dirname(g.__file__), "apworld_template")

TEMPLATES = [
    "Locations.py.j2",
    "Items.py.j2",
    "Options.py.j2",
    "Types.py.j2",
    "Regions.py.j2",
    "Rules.py.j2",
    "__init__.py.j2",
]


def _track(uri, title, artist):
    return GenericTrack(
        uri=uri, title=title, artist=artist, album_title="o", duration_ms=1000, service="local"
    )


def _album(uri, n, artist):
    # deliberately reuse track titles across albums so collisions are likely
    tr = [_track(f"{uri}/{i}", ["Intro", "Outro", "Jam", "Intro"][i % 4], artist) for i in range(n)]
    return GenericAlbum(
        uri=uri,
        title=uri,
        artist=artist,
        image_url="",
        total_tracks=n,
        album_type="Album",
        service="local",
        tracks=tr,
    )


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """Render every template once for the module and return (text-by-name, metas)."""
    src = [_album("alb1", 6, "Bandit"), _album("alb2", 6, "Bandit"), _album("alb3", 5, "Other")]
    metas = g.build_meta_albums(src, mode="packs", count=3, seed=7)

    env = Environment(loader=FileSystemLoader(TPL))
    env.filters["to_ascii"] = filter_to_ascii
    env.filters["py_json"] = filter_py_json
    ctx = {"apworld_data": metas, "apworld_name": "TestMeta"}

    out = tmp_path_factory.mktemp("rendered")
    texts = {}
    for tname in TEMPLATES:
        txt = env.get_template(tname).render(ctx)
        texts[tname] = txt
        path = os.path.join(out, tname[:-3])  # strip .j2
        with open(path, "w", encoding="utf-8") as f:
            f.write(txt)
        py_compile.compile(path, doraise=True)  # must be valid Python
    return texts, metas


def test_all_templates_compile(rendered):
    texts, _ = rendered
    assert set(texts) == set(TEMPLATES)  # render+compile happened in fixture


def test_location_names_unique_and_complete(rendered):
    texts, metas = rendered
    locs = re.findall(r'^\s*("(?:[^"\\]|\\.)*")\s*:\s*LocData\(', texts["Locations.py.j2"], re.M)
    assert locs, "no locations parsed"
    assert len(locs) == len(set(locs)), "DUPLICATE LOCATION NAMES!"
    total_tracks = sum(len(m.tracks) for m in metas)
    assert len(locs) == total_tracks


def test_album_items_unique(rendered):
    texts, metas = rendered
    items = re.findall(r'("(?:[^"\\]|\\.)*"):\s*ItemData\(1000', texts["Items.py.j2"])
    assert len(items) == len(metas) == len(set(items))


def test_victory_count_matches_album_count(rendered):
    texts, metas = rendered
    m = re.search(
        r"completion_condition\[player\]\s*=\s*lambda state: "
        r'state\.has\("Album finished!", player, (\d+)\)',
        texts["Rules.py.j2"],
    )
    assert m and int(m.group(1)) == len(metas)


def test_trap_item_and_slotdata_rendered(rendered):
    """A1: the reference trap is baked into item_table with trap classification, the
    fill_slot_data ``traps`` block is present (names match the trap dict), the trap options
    exist, and the inherited edgy stub is gone. The whole world already compiles (fixture)."""
    texts, _ = rendered
    items, init, opts = texts["Items.py.j2"], texts["__init__.py.j2"], texts["Options.py.j2"]

    # Reference trap present with trap classification; old stub removed.
    assert re.search(r'"Bad Track Trap":\s*ItemData\(\d+,\s*ItemClassification\.trap', items)
    assert "Forcefem" not in items
    # trap_items feeds both item_table and slot_data names.
    assert "trap_items" in items and "**trap_items" in items
    assert '"traps"' in init and '"enabled"' in init and "trap_items.keys()" in init
    # Options exist and are wired into the dataclass.
    assert "class EnableTraps(Toggle)" in opts and "class TrapPercentage(Range)" in opts
    assert "EnableTraps:" in opts and "TrapPercentage:" in opts


def test_shuffle_trap_item_rendered(rendered):
    """The flagship Shuffle Trap is baked into trap_items/trap_weights with trap
    classification and a unique id; fill_slot_data emits all trap names from trap_items."""
    texts, _ = rendered
    items = texts["Items.py.j2"]

    # Shuffle Trap present with trap classification.
    assert re.search(r'"Shuffle Trap":\s*ItemData\(\d+,\s*ItemClassification\.trap', items)
    # Weighted in trap_weights alongside the reference trap.
    assert re.search(r'"Shuffle Trap":\s*\d+', items)

    # Every trap item id is unique (no collision between Bad Track / Shuffle).
    trap_ids = re.findall(r'"[^"]+ Trap":\s*ItemData\((\d+),\s*ItemClassification\.trap', items)
    assert len(trap_ids) >= 2 and len(trap_ids) == len(set(trap_ids))


def test_subset_shrinks_rendered_location_count(tmp_path):
    """A5: a `subset=K` build must bake exactly K AP locations into the rendered
    world — proving the check-count knob really shrinks the location pool."""
    src = [
        _album("alb1", 6, "Bandit"),
        _album("alb2", 6, "Bandit"),
        _album("alb3", 5, "Other"),
    ]  # 17 tracks
    metas = g.build_meta_albums(src, mode="packs", count=3, seed=7, subset=8)
    assert sum(len(m.tracks) for m in metas) == 8

    env = Environment(loader=FileSystemLoader(TPL))
    env.filters["to_ascii"] = filter_to_ascii
    env.filters["py_json"] = filter_py_json
    txt = env.get_template("Locations.py.j2").render(
        {"apworld_data": metas, "apworld_name": "Subset"}
    )
    path = os.path.join(tmp_path, "Locations.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)
    py_compile.compile(path, doraise=True)

    locs = re.findall(r'^\s*("(?:[^"\\]|\\.)*")\s*:\s*LocData\(', txt, re.M)
    assert len(locs) == len(set(locs)) == 8  # K unique locations, not 17
