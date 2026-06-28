#!/usr/bin/env python3
"""Turn a Musipelago .apworld into a playable single-player Archipelago seed.

Cross-platform (Windows/macOS/Linux), stdlib only. Ships with musipelago so anyone
can go from a generated world to a hostable seed:

    python tools/make_seed.py /path/to/Musipelago_<name>.apworld --ap-dir /path/to/Archipelago

The gen app builds the .apworld (+ a sibling catalog .json and a starter .yaml); this
installs the world into Archipelago's custom_worlds/, runs Generate.py with an isolated
player-files dir (so it can't pick up stray YAMLs), verifies the seed is single-player,
and copies the catalog next to it.

Archipelago itself (a checkout/install with Generate.py) is required and located via
--ap-dir, then $ARCHIPELAGO_DIR, then auto-detection. Run this with a Python that has
Archipelago's dependencies available (e.g. the same env you run Generate.py in).
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile


def resolve_ap_dir(arg=None):
    """Find an Archipelago directory (has Generate.py + custom_worlds/)."""
    candidates = [
        arg,
        os.environ.get("ARCHIPELAGO_DIR"),
        os.path.join(os.path.expanduser("~"), "Archipelago"),
    ]
    for c in candidates:
        if (
            c
            and os.path.isfile(os.path.join(c, "Generate.py"))
            and os.path.isdir(os.path.join(c, "custom_worlds"))
        ):
            return os.path.abspath(c)
    return None


def default_yaml(game, slot=None):
    """A minimal, valid single-player YAML for a Musipelago world."""
    slot = (slot or game.replace("Musipelago_", ""))[:16] or "Player1"
    return (
        f"name: {slot}\n"
        f"game: {game}\n"
        f"{game}:\n"
        f"  StartingAlbum: album_001\n"
        f"  AllowPlayingAnyTrack: true\n"
    )


def players_from_zip(zip_path):
    """Read the spoiler from an AP_*.zip and return the Players count (or None)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            spoiler = next((n for n in zf.namelist() if "Spoiler" in n), None)
            if not spoiler:
                return None
            for line in zf.read(spoiler).decode("utf-8", "replace").splitlines():
                if line.startswith("Players:"):
                    try:
                        return int(line.split(":", 1)[1].strip())
                    except ValueError:
                        return None
    except Exception:
        return None
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build an AP seed from a Musipelago .apworld.")
    ap.add_argument("apworld", help="Path to Musipelago_<name>.apworld")
    ap.add_argument("--ap-dir", help="Archipelago directory (with Generate.py).")
    ap.add_argument("--yaml", help="Player YAML (default: sibling .yaml, else synthesized).")
    ap.add_argument("--output", help="Seed output dir (default: <apworld-dir>/<name>-seed).")
    ap.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to run Generate.py (default: this one).",
    )
    ap.add_argument("--slug", help="Override the seed subfolder name.")
    args = ap.parse_args(argv)

    apworld = os.path.abspath(args.apworld)
    if not os.path.isfile(apworld):
        ap.error(f"apworld not found: {apworld}")
    base = os.path.basename(apworld)
    if not (base.startswith("Musipelago_") and base.endswith(".apworld")):
        ap.error(f"expected a Musipelago_<name>.apworld, got '{base}'")
    game = base[: -len(".apworld")]  # Musipelago_<name>
    name = game[len("Musipelago_") :]

    ap_dir = resolve_ap_dir(args.ap_dir)
    if not ap_dir:
        ap.error(
            "Could not find Archipelago. Pass --ap-dir /path/to/Archipelago "
            "(the folder containing Generate.py), or set $ARCHIPELAGO_DIR."
        )

    # 1. Install the apworld (left in place — the server needs it to host).
    dest = os.path.join(ap_dir, "custom_worlds", base)
    if os.path.abspath(dest) != apworld:
        shutil.copy2(apworld, dest)
    print(f"==> Installed {base} into custom_worlds/ (kept for hosting)")

    # 2. Isolated player-files dir with exactly one YAML.
    out = os.path.abspath(args.output or os.path.join(os.path.dirname(apworld), f"{name}-seed"))
    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        if args.yaml and os.path.isfile(args.yaml):
            shutil.copy2(args.yaml, os.path.join(tmp, "player.yaml"))
            print(f"==> Using YAML: {args.yaml}")
        else:
            sibling = apworld[: -len(".apworld")] + ".yaml"
            if os.path.isfile(sibling):
                shutil.copy2(sibling, os.path.join(tmp, "player.yaml"))
                print(f"==> Using sibling YAML: {sibling}")
            else:
                with open(os.path.join(tmp, "player.yaml"), "w", encoding="utf-8") as f:
                    f.write(default_yaml(game))
                print("==> No YAML provided; synthesized a minimal default")

        # 3. Generate.
        print(f"==> Generating seed for {game}")
        subprocess.run(
            [
                args.python,
                "Generate.py",
                "--player_files_path",
                tmp,
                "--outputpath",
                out,
                "--spoiler",
                "2",
            ],
            cwd=ap_dir,
            check=True,
        )

    # 4. Verify single-player.
    zips = sorted(glob.glob(os.path.join(out, "AP_*.zip")), key=os.path.getmtime)
    if not zips:
        print(f"FAIL: no AP_*.zip produced in {out}", file=sys.stderr)
        return 1
    seed = zips[-1]
    players = players_from_zip(seed)
    print(f"==> Spoiler reports Players: {players}")
    if players != 1:
        print(f"FAIL: expected Players: 1, got {players}", file=sys.stderr)
        return 1

    # 5. Copy the catalog the client needs (sibling of the apworld), if present.
    catalog = apworld[: -len(".apworld")] + ".json"
    if os.path.isfile(catalog):
        shutil.copy2(catalog, out)
        print(f"==> Copied catalog {os.path.basename(catalog)} into the seed dir")
    else:
        print(f"WARN: catalog '{game}.json' not found next to the apworld; the client needs it.")

    print()
    print(f"==> Done. Seed: {seed}")
    print(f'    Host:   cd "{ap_dir}" && python MultiServer.py "{seed}"')
    print(f"    Client: run musipelago-client, load {game}.json, connect localhost:38281")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
