"""Unit tests for the shipped cross-platform seed helper (tools/make_seed.py).

Only the pure helpers are tested here (no actual Generate.py run — that's the
end-to-end check). The module is loaded from tools/ which isn't on the package path.
"""
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import make_seed as m  # noqa: E402


def test_default_yaml_game_name_and_capped_slot():
    y = m.default_yaml("Musipelago_A_Very_Long_World_Name")
    assert "game: Musipelago_A_Very_Long_World_Name" in y
    assert "name: A_Very_Long_Wor" in y          # slot capped to 16 chars
    assert "StartingAlbum: album_001" in y
    assert "AllowPlayingAnyTrack: true" in y


def test_resolve_ap_dir_prefers_valid_arg(tmp_path):
    ap = tmp_path / "AP"
    (ap / "custom_worlds").mkdir(parents=True)
    (ap / "Generate.py").write_text("# stub")
    assert m.resolve_ap_dir(str(ap)) == os.path.abspath(str(ap))


def test_resolve_ap_dir_rejects_incomplete(tmp_path):
    # has Generate.py but no custom_worlds/ -> not a valid AP dir
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "Generate.py").write_text("# stub")
    assert m.resolve_ap_dir(str(bad)) is None


def test_players_from_zip_reads_spoiler(tmp_path):
    z = tmp_path / "AP_123.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("AP_123_Spoiler.txt", "Archipelago Version 1.0\nPlayers: 1\nGame: x\n")
    assert m.players_from_zip(str(z)) == 1


def test_players_from_zip_handles_missing_spoiler(tmp_path):
    z = tmp_path / "AP_456.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("other.txt", "no spoiler here")
    assert m.players_from_zip(str(z)) is None
