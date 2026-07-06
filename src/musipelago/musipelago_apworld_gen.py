import ctypes
import dataclasses
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import zipfile

import requests
from kivy.config import Config
from kivy.logger import Logger

from musipelago import theme as theme
from musipelago.utils import resource_path

try:
    # Query Windows for screen size
    user32 = ctypes.windll.user32
    screen_width = user32.GetSystemMetrics(0)
    screen_height = user32.GetSystemMetrics(1)

    target_w = 1024
    target_h = 768

    # Add a buffer for taskbar/decorations (e.g. 50px)
    if screen_width < (target_w + 50) or screen_height < (target_h + 50):
        # Screen is too small: Configure Kivy to start MAXIMIZED
        Config.set("graphics", "window_state", "maximized")
        # We still set a minimum size just in case
        Config.set("graphics", "width", "800")
        Config.set("graphics", "height", "600")
        Logger.info("Window: Screen too small. Configured to start maximized.")
    else:
        # Screen is large enough: Configure EXACT SIZE
        Config.set("graphics", "width", str(target_w))
        Config.set("graphics", "height", str(target_h))

        # Optional: Force centering (Kivy usually centers by default if size is set here)
        # Config.set('graphics', 'position', 'auto')
        Logger.info(f"Window: Configured to {target_w}x{target_h}.")

except Exception as e:
    Logger.warning(f"Window Config Error: {e}. Using default 1024x768.")
    Config.set("graphics", "width", "1024")
    Config.set("graphics", "height", "768")
Config.set("input", "mouse", "mouse,disable_multitouch")

from kivy.core.text import DEFAULT_FONT, LabelBase

try:
    font_path = resource_path(os.path.join("resources", "NotoSansJP-Regular.ttf"))
    LabelBase.register(DEFAULT_FONT, font_path)
    Logger.info(f"Font: Registered default font: {font_path}")
except Exception as e:
    Logger.error(f"Font: Failed to register custom font: {e}")

from jinja2 import Environment, FileSystemLoader
from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    ColorProperty,
    ListProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.resources import resource_add_path
from kivy.storage.jsonstore import JsonStore
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.togglebutton import ToggleButton

from musipelago.backends import (
    GenericAlbum,
    GenericArtist,
    GenericPlaylist,
)
from musipelago.plugin_loader import PluginManager

# --- Local Imports ---
from musipelago.utils import (
    KIVY_ICON,
    corpus_stats,
    filter_py_json,
    filter_to_ascii,
    format_hm,
    pack_layout_summary,
)
from musipelago.utils_client import format_hms

# Not necessary per se, but fixes PyInstaller build
# import musipelago.client_ui_components


class AsyncImageWithHeaders(Image):
    web_source = StringProperty(None)
    _cache_dir = ""
    _cache_path = ""
    _headers = {}  # Will be set by the app after login

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not AsyncImageWithHeaders._cache_dir:
            app_dir = App.get_running_app().user_data_dir
            AsyncImageWithHeaders._cache_dir = os.path.join(app_dir, "image_cache")
            if not os.path.exists(AsyncImageWithHeaders._cache_dir):
                os.makedirs(AsyncImageWithHeaders._cache_dir)

        # Set default headers
        if not AsyncImageWithHeaders._headers:
            AsyncImageWithHeaders._headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )

    def on_web_source(self, instance, url):
        if not url:
            self.source = KIVY_ICON
            return

        if url.startswith("http://") or url.startswith("https://"):
            filename = hashlib.md5(url.encode("utf-8")).hexdigest() + ".jpg"
            self._cache_path = os.path.join(AsyncImageWithHeaders._cache_dir, filename)

            if os.path.exists(self._cache_path):
                self.source = self._cache_path
            else:
                self.source = KIVY_ICON
                thread = threading.Thread(target=self._download_image, args=(url, self._cache_path))
                thread.start()
        else:
            self.source = url

    def _download_image(self, url, cache_path):
        try:
            response = requests.get(url, headers=self._headers, stream=True)
            if response.status_code == 200:
                with open(cache_path, "wb") as f:
                    response.raw.decode_content = True
                    shutil.copyfileobj(response.raw, f)
                Clock.schedule_once(lambda dt: self._set_source(cache_path))
            else:
                Logger.error(f"ImageDownloader: Failed {url}, status {response.status_code}")
        except Exception as e:
            Logger.error(f"ImageDownloader: Exception for {url}: {e}")

    def _set_source(self, cache_path):
        if self._cache_path == cache_path:
            self.source = cache_path

    @classmethod
    def set_http_headers(cls, headers: dict):
        cls._headers = headers


class CustomLoginPopup(Popup):
    """
    A generic popup that hosts a widget provided by a plugin.
    """

    def __init__(self, login_widget: object, backend: object, **kwargs):
        super().__init__(**kwargs)
        self.title = f"Login to {backend.service_name.capitalize()}"
        self.size_hint = (0.9, None)
        self.auto_dismiss = False

        self.backend = backend
        self.login_widget = login_widget

        # Build the popup content
        main_layout = BoxLayout(orientation="vertical", spacing="10dp", padding="10dp")

        # Add the plugin's custom UI
        main_layout.add_widget(self.login_widget)

        # Add standard buttons
        button_layout = BoxLayout(size_hint_y=None, height="44dp", spacing="10dp")
        cancel_btn = Button(text="Cancel", on_release=self.dismiss)
        login_btn = Button(text="Login", on_release=self.on_login_press)
        button_layout.add_widget(cancel_btn)
        button_layout.add_widget(login_btn)

        main_layout.add_widget(button_layout)

        self.content = main_layout
        self.height = getattr(login_widget, "desired_popup_height", dp(400))

    def on_login_press(self, instance):
        """
        Passes the login widget back to the backend's login method.
        """
        Logger.info(f"CustomLoginPopup: Calling {self.backend.service_name}.login()")
        # The backend's login method will handle threading
        self.backend.login(login_widget=self.login_widget)
        self.dismiss()


class LoginPopup(Popup):
    def __init__(self, app_instance, **kwargs):
        super().__init__(**kwargs)
        self.title = "Select Service"
        self.size_hint = (0.8, 0.6)
        self.auto_dismiss = False
        self.app = app_instance
        self.friendly_to_module_map = {}

        layout = BoxLayout(orientation="vertical", padding=10, spacing=10)
        layout.add_widget(Label(text="Musipelago", font_size="24sp"))
        layout.add_widget(Label(text="Please select a music service to connect."))

        # --- NEW SPINNER ---
        layout.add_widget(Label(text="Service:"))
        self.backend_spinner = Spinner(
            text="No plugins found", values=[], size_hint_y=None, height="44dp"
        )
        layout.add_widget(self.backend_spinner)
        # --- END NEW ---

        self.status_label = Label(text="Status: Not Logged In", size_hint_y=0.4)
        layout.add_widget(self.status_label)

        self.login_button = Button(
            text="Connect", on_press=self.authenticate, size_hint_y=None, height="48dp"
        )
        layout.add_widget(self.login_button)

        self.content = layout

    def authenticate(self, instance):
        if self.backend_spinner.text == "No plugins found":
            self.status_label.text = "Error: Cannot login, no plugins loaded."
            return

        selected_friendly_name = self.backend_spinner.text
        selected_backend_name = self.friendly_to_module_map.get(selected_friendly_name)

        if not selected_backend_name:
            self.app.on_login_failure(f"Could not find plugin for: {selected_friendly_name}")
            return

        # --- MODIFIED ---
        # 1. Get the 'generator' class for the selected plugin
        BackendClass = self.app.plugin_manager.get_plugin_component_class(
            selected_backend_name, "generator_backend"
        )
        # --- END MODIFY ---

        if not BackendClass:
            self.app.on_login_failure(f"Could not load plugin: {selected_backend_name}")
            return

        # 2. Instantiate the backend
        self.app.backend = BackendClass(
            service_name_key=selected_backend_name,  # <-- Pass the key
            on_login_success=self.app.on_login_success,
            on_login_failure=self.app.on_login_failure,
        )

        Logger.info(f"LoginPopup: Authenticating with {selected_backend_name}")
        self.login_button.disabled = True
        self.status_label.text = "Initializing login..."

        # Pre-fill the remembered folder (Local Files) so get_login_ui starts there.
        last_dir = self.app._load_gen_setting("last_directory")
        if last_dir and hasattr(self.app.backend, "root_directory"):
            self.app.backend.root_directory = last_dir

        # 3. Ask the backend for its login UI (this logic is unchanged)
        try:
            login_widget = self.app.backend.get_login_ui()
        except Exception as e:
            Logger.error(f"Plugin Error: {selected_backend_name}.get_login_ui() failed: {e}")
            self.app.on_login_failure(f"Plugin error: {e}")
            return

        # 4. Decide on the login strategy (this logic is unchanged)
        if login_widget is None:
            # External Login
            Logger.info("LoginPopup: Backend provided no UI. Assuming external login.")
            Window.minimize()
            self.app.backend.login(login_widget=None)
            self.dismiss()
        else:
            # Custom UI Login (Subsonic)
            Logger.info("LoginPopup: Backend provided a custom UI. Showing CustomLoginPopup.")
            custom_popup = CustomLoginPopup(login_widget=login_widget, backend=self.app.backend)
            custom_popup.open()
            self.dismiss()


def _balanced_grid(tracks, packs, size, target_ms=None, rng=None):
    """Fixed `packs` x `size` grid with duration-balanced assignment (A5b).

    The track pool is pre-shuffled by build_meta_albums, so the first `need = packs*size` tracks
    are a seeded random sample (the user chose random selection over biasing which songs are
    picked). We then distribute those tracks into bins of capacity `size`, longest-first (LPT):
    each track lands in the eligible (not-yet-full) bin that keeps the layout most even — the
    currently-lightest bin, or with `target_ms` the bin whose total stays closest to the target.
    This clusters pack run-times tightly around the draw's natural mean instead of the lumpy
    near-equal split the 'packs'/'per_pack' modes produce.

    LPT processes longest-first, so each bin comes out sorted longest->shortest; with `rng` given
    we re-shuffle WITHIN each pack afterward so the play order isn't predictably descending. This
    only reorders tracks inside a pack — membership and per-pack duration balance are unchanged.

    Grid stays exact when the pool is large enough (pool >= packs*size -> exactly that grid;
    extra tracks are dropped). With too few tracks it keeps `size` and makes ceil(pool/size)
    packs of <= size (fewer than `packs`, never empty). Pure (no Kivy)."""
    packs = max(1, int(packs))
    size = max(1, int(size or 1))
    need = min(packs * size, len(tracks))
    if need <= 0:
        return [tracks] if tracks else []
    drawn = tracks[:need]
    bins_n = min(packs, (need + size - 1) // size)  # ceil(need/size), capped at `packs`
    bins = [[] for _ in range(bins_n)]
    sums = [0] * bins_n
    for t in sorted(drawn, key=lambda x: getattr(x, "duration_ms", 0) or 0, reverse=True):
        d = getattr(t, "duration_ms", 0) or 0
        best, best_key = None, None
        for b in range(bins_n):
            if len(bins[b]) >= size:  # respect the capacity-M cap
                continue
            key = abs(sums[b] + d - target_ms) if target_ms else sums[b]
            if best is None or key < best_key:
                best, best_key = b, key
        bins[best].append(t)
        sums[best] += d
    if rng is not None:
        for b in bins:
            rng.shuffle(b)  # mix up the within-pack order (LPT leaves it longest-first)
    return [b for b in bins if b]


def _chunk(tracks, mode, count, *, size=None, target_ms=None, rng=None):
    """Split `tracks` into groups. mode='per_pack' -> groups of ~count tracks;
    mode='packs' -> `count` near-equal groups (never empty when count <= len);
    mode='minutes' -> greedily fill packs to ~`count` minutes each (each track
    lands in whichever boundary leaves the pack closest to the target length);
    mode='grid' -> `count` packs of `size` tracks, duration-balanced (_balanced_grid;
    `rng` re-shuffles within each pack so order isn't longest-first)."""
    count = max(1, int(count))
    if mode == "grid":
        return _balanced_grid(tracks, packs=count, size=size, target_ms=target_ms, rng=rng)
    if mode == "per_pack":
        return [tracks[i : i + count] for i in range(0, len(tracks), count)]
    if mode == "minutes":
        target_ms = count * 60 * 1000
        groups, cur, cur_ms = [], [], 0
        for t in tracks:
            d = getattr(t, "duration_ms", 0) or 0
            # Close the current pack before this track only if doing so leaves
            # it closer to the target than overshooting would. Tracks are
            # pre-shuffled by build_meta_albums, so order is already random.
            if (
                cur
                and cur_ms + d > target_ms
                and abs(cur_ms - target_ms) <= abs(cur_ms + d - target_ms)
            ):
                groups.append(cur)
                cur, cur_ms = [], 0
            cur.append(t)
            cur_ms += d
        if cur:
            groups.append(cur)
        return groups or [tracks]
    # 'packs': split into `count` near-equal groups, capped so none are empty.
    n = min(count, len(tracks)) or 1
    base, rem = divmod(len(tracks), n)
    groups, start = [], 0
    for i in range(n):
        size = base + (1 if i < rem else 0)
        groups.append(tracks[start : start + size])
        start += size
    return groups


def build_meta_albums(
    albums,
    *,
    mode,
    count,
    seed=None,
    subset=None,
    subset_minutes=None,
    shuffle=True,
    pack_size=None,
    target_minutes=None,
):
    """Regroup the (already curated) tracks across `albums` into synthetic
    "Mixtape" meta-albums at generate time. This is a pure function of its
    inputs: it returns a fresh list of GenericAlbum objects and never mutates
    the source albums, so each generation can re-roll a different layout.

    Tracks are partitioned (each source track lands in exactly one meta-album),
    never sampled with replacement, so no duplicate location IDs are produced.
    Each meta-album gets a unique synthetic artist/title/uri (item, region and
    state.has rules key off "[artist] [title]"), and a per-pack uniqueness pass
    suffixes duplicate track titles so two same-named tracks in one pack don't
    collide into the same location name. Real track uris are preserved, so the
    client plays the correct underlying files regardless of grouping.

    Randomizer controls (A5):
    - `shuffle` (default True): randomize track order before packing. Off keeps
      the source catalog order (deterministic, seed-independent).
    - `subset`: keep only this many tracks as checks. A positive int < the pool
      size truncates after shuffling, so with `shuffle` on this is a seeded
      random sample of K tracks; with `shuffle` off it's the first K in catalog
      order. None/0/>= pool size keeps every track. Fewer tracks => fewer AP
      locations, baked into the generated `.apworld`. Ignored in 'grid' mode
      (the grid's count*pack_size defines the track count).
    - `subset_minutes`: a duration budget (in minutes) analogous to `subset` but
      by playtime. Applied after shuffle and after the count `subset`, it keeps
      tracks in order until their cumulative `duration_ms` reaches the budget
      (including the track that crosses it, so total >= budget), then drops the
      rest. Tracks with unknown duration don't advance the budget. None/0
      disables; ignored in 'grid' mode.
    - `pack_size`/`target_minutes` ('grid' mode only): exact `count` packs of
      `pack_size` songs each, duration-balanced toward an optional soft
      `target_minutes` per pack (see _balanced_grid).
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    # Tag each track with its origin album (name + cover) before flattening, so a track
    # regrouped into a Mixtape still knows where it came from. The client shows the real album
    # in the now-playing bar + the origin cover, even though album_title becomes "Mixtape NN".
    tracks = [
        dataclasses.replace(
            t,
            source_album=album.title,
            source_image_url=album.display_image_url or album.image_url,
        )
        for album in albums
        for t in album.tracks
    ]
    if not tracks:
        return albums
    if shuffle:
        rng.shuffle(tracks)
    # 'grid' derives its own track count (count*pack_size) inside _balanced_grid;
    # the global subset caps only apply to the other modes.
    if mode != "grid" and subset and 0 < int(subset) < len(tracks):
        tracks = tracks[: int(subset)]
    if mode != "grid" and subset_minutes and int(subset_minutes) > 0:
        budget_ms = int(subset_minutes) * 60 * 1000
        kept, acc = [], 0
        for t in tracks:
            kept.append(t)
            acc += t.duration_ms or 0
            if acc >= budget_ms:
                break
        tracks = kept
    target_ms = target_minutes * 60 * 1000 if target_minutes else None
    groups = _chunk(tracks, mode, count, size=pack_size, target_ms=target_ms, rng=rng)
    service = albums[0].service if albums else "local"
    metas = []
    for i, group in enumerate(groups, start=1):
        title = f"Mixtape {i:02d}"
        seen, fixed = set(), []
        for track in group:
            name, n = track.title, 2
            while (track.artist, name) in seen:  # within-pack title collision guard
                name = f"{track.title} ({n})"
                n += 1
            seen.add((track.artist, name))
            # keep real uri/artist/duration/service; only retitle for uniqueness
            fixed.append(dataclasses.replace(track, title=name, album_title=title))
        metas.append(
            GenericAlbum(
                uri=f"meta:{i:02d}",
                title=title,
                artist="Musipelago",
                image_url="",
                total_tracks=len(fixed),
                album_type="Mixtape",
                service=service,
                tracks=fixed,
            )
        )
    return metas


def _open_path(path):
    """Open a folder in the OS file manager (cross-platform, best-effort)."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        Logger.warning(f"Generate: could not open folder {path}: {e}")


def build_starter_yaml(apworld_name):
    """A minimal, ready-to-edit Archipelago YAML for a generated Musipelago world.
    Pure (testable). The slot name is capped at 16 chars (AP truncates it); the
    game key must equal the apworld's game name `Musipelago_<name>`."""
    game = f"Musipelago_{apworld_name}"
    slot = apworld_name[:16] or "Player1"
    return (
        f"# Starter YAML for {game}. Edit the slot name/options as you like, then\n"
        f"# build a seed:  ~/repos/AP/games/musipelago/gen.sh <this-world>.apworld\n"
        f"name: {slot}\n"
        f"game: {game}\n"
        f"{game}:\n"
        f"  StartingAlbum: album_001\n"
        f"  AllowPlayingAnyTrack: true\n"
    )


class GeneratePopup(Popup):
    apworld_data = ObjectProperty(None)  # This will be a list of GenericAlbum

    # Dry-run layout preview line (bound to a Label in the kv). Recomputed —
    # debounced — whenever the mixtape controls change; see _refresh_preview.
    preview_text = StringProperty("")

    def __init__(self, apworld_data, **kwargs):
        super().__init__(**kwargs)
        self.apworld_data = apworld_data  # List of GenericAlbum objects
        self._preview_ev = None

    def _schedule_preview(self, *args):
        """Debounce preview recomputes so typing in a numeric field doesn't
        rebuild the layout per keystroke."""
        if self._preview_ev is not None:
            self._preview_ev.cancel()
        self._preview_ev = Clock.schedule_once(self._refresh_preview, 0.3)

    def _refresh_preview(self, *args):
        """Recompute the pack-layout preview from the live controls. When the
        mixtape randomizer is enabled, this dry-runs build_meta_albums with the
        current config (rolling + backfilling a seed when the field is blank so
        the eventual generation reproduces exactly what was previewed); when it
        is disabled it summarizes the real albums as-is."""
        if "meta_preview" not in self.ids:  # kv not built yet
            return
        albums = self.apworld_data or []
        cfg = self._read_meta_config()
        if cfg.get("enabled"):
            translated = {k: v for k, v in cfg.items() if k != "enabled"}
            # build_meta_albums(seed=None) would use a fresh RNG, so the preview
            # wouldn't match generation. Roll a seed, show it, and preview with it.
            if translated.get("seed") is None and "meta_seed" in self.ids:
                rolled = random.randrange(0, 2**31)
                self.ids.meta_seed.text = str(rolled)
                translated["seed"] = rolled
            try:
                metas = build_meta_albums(albums, **translated)
            except Exception as e:
                Logger.warning(f"Preview: could not build layout: {e}")
                self.preview_text = "Preview: unavailable for the current settings."
                return
            self.preview_text = self._format_preview(pack_layout_summary(metas), enabled=True)
        else:
            self.preview_text = self._format_preview(pack_layout_summary(albums), enabled=False)

    @staticmethod
    def _format_preview(summary, *, enabled):
        """One-line pack-layout preview from a pack_layout_summary dict."""
        n = summary["n_packs"]
        if not n:
            return "Preview: add albums to see the pack layout."
        unit = "pack" if enabled else "album"
        label = "Preview" if enabled else "Preview (no regrouping)"
        n_tracks = summary["n_tracks"]
        lo, med, hi = summary["min_min"], summary["median_min"], summary["max_min"]
        span = f"{lo} min/{unit}" if lo == hi else f"{lo}–{hi} min/{unit} (median {med})"
        return (
            f"{label}: {n} {unit}{'s' if n != 1 else ''} · "
            f"{n_tracks} track{'s' if n_tracks != 1 else ''} · {span}"
        )

    def on_popup_generate(self, apworld_name):
        app = App.get_running_app()
        if not apworld_name.strip():
            app.root.status_text = "Error: APWorld name cannot be empty."
            return

        meta_config = self._read_meta_config()

        # Run file generation in a thread to avoid blocking UI
        threading.Thread(target=self.generate_files, args=(apworld_name, meta_config)).start()
        self.dismiss()

    def _read_meta_config(self):
        """Read the meta-album controls from the popup. Returns a dict; when
        disabled (or controls absent) the generator uses the real albums."""
        ids = self.ids
        if "meta_enable" not in ids or ids.meta_enable.state != "down":
            return {"enabled": False}
        mode = {
            "N packs": "packs",
            "Tracks per pack": "per_pack",
            "Minutes per pack": "minutes",
            "Balanced grid": "grid",
        }.get(ids.meta_mode.text, "packs")
        try:
            count = int(ids.meta_count.text)
        except (ValueError, AttributeError):
            count = 0
        seed_text = (ids.meta_seed.text or "").strip()
        seed = int(seed_text) if seed_text else None
        subset_text = (ids.meta_subset.text or "").strip() if "meta_subset" in ids else ""
        try:
            subset = int(subset_text) if subset_text else None
        except ValueError:
            subset = None
        subset_min_text = (
            (ids.meta_subset_min.text or "").strip() if "meta_subset_min" in ids else ""
        )
        try:
            subset_minutes = int(subset_min_text) if subset_min_text else None
        except ValueError:
            subset_minutes = None
        shuffle = ids.meta_shuffle.state == "down" if "meta_shuffle" in ids else True
        # 'Balanced grid' (mode='grid') extras: songs-per-pack (M) + optional target min/pack.
        try:
            pack_size = int(ids.meta_pack_size.text) if "meta_pack_size" in ids else None
        except (ValueError, AttributeError):
            pack_size = None
        target_text = (ids.meta_target_min.text or "").strip() if "meta_target_min" in ids else ""
        try:
            target_minutes = int(target_text) if target_text else None
        except ValueError:
            target_minutes = None
        return {
            "enabled": True,
            "mode": mode,
            "count": count,
            "seed": seed,
            "subset": subset,
            "subset_minutes": subset_minutes,
            "shuffle": shuffle,
            "pack_size": pack_size,
            "target_minutes": target_minutes,
        }

    def generate_files(self, apworld_name, meta_config=None):
        app = App.get_running_app()
        Clock.schedule_once(
            lambda dt: setattr(app.root, "status_text", f"Generation started for: {apworld_name}")
        )
        Logger.info(f"Generate: Button clicked for {apworld_name}")

        try:
            template_dir = resource_path("apworld_template")
            # Write to the user's remembered output folder (default ~/Musipelago),
            # not buried in the package. Artifacts (.apworld/.json/.yaml) are siblings
            # in this root; output_dir holds the rendered world files for zipping.
            base_dir = app.output_root()
            output_dir = os.path.join(base_dir, "Musipelago_" + apworld_name)

            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

            Logger.info(f"Generate: Reading templates from: {template_dir}")
            Logger.info(f"Generate: Saving files to: {output_dir}")
        except Exception as e:
            Clock.schedule_once(
                lambda dt: setattr(
                    app.root, "status_text", "Error: Could not find template directory."
                )
            )
            Logger.error(f"Generate: Failed to access directories: {e}")
            return

        try:
            env = Environment(loader=FileSystemLoader(template_dir))
            env.filters["to_ascii"] = filter_to_ascii
            env.filters["py_json"] = filter_py_json

            files_to_generate = [
                "Locations.py.j2",
                "Items.py.j2",
                "Options.py.j2",
                "Types.py.j2",
                "Regions.py.j2",
                "Rules.py.j2",
                "__init__.py.j2",
                "archipelago.json.j2",
            ]

            # Optionally regroup tracks into randomized meta-albums at generate
            # time. effective_data drives BOTH the templates and the JSON catalog
            # so they stay consistent; the UI's real-album list is never mutated.
            if meta_config and meta_config.get("enabled"):
                effective_data = build_meta_albums(
                    self.apworld_data,
                    mode=meta_config["mode"],
                    count=meta_config["count"],
                    seed=meta_config.get("seed"),
                    subset=meta_config.get("subset"),
                    subset_minutes=meta_config.get("subset_minutes"),
                    shuffle=meta_config.get("shuffle", True),
                    pack_size=meta_config.get("pack_size"),
                    target_minutes=meta_config.get("target_minutes"),
                )
                total = sum(len(a.tracks) for a in self.apworld_data)
                used = sum(len(a.tracks) for a in effective_data)
                Clock.schedule_once(
                    lambda dt: setattr(
                        app.root,
                        "status_text",
                        f"Using {used} of {total} tracks across {len(effective_data)} meta-albums.",
                    )
                )
            else:
                effective_data = self.apworld_data

            # The context now uses the generic data models
            context = {
                "apworld_data": effective_data,  # List of GenericAlbum
                "apworld_name": apworld_name,
            }

            for template_name in files_to_generate:
                Logger.info(f"Generate: Processing template: {template_name}")
                template = env.get_template(template_name)
                processed_content = template.render(context)

                output_filename = template_name.rsplit(".j2", 1)[0]
                output_file_path = os.path.join(output_dir, output_filename)

                with open(output_file_path, "w", encoding="utf-8") as f:
                    f.write(processed_content)

            Logger.info("Generate: Creating simplified JSON file...")

            # 1. Build the "apworld" key (for AP name mapping)
            apworld_content = []
            for album in effective_data:  # album is GenericAlbum
                album_name_str = f"[{album.artist}] [{album.title}]"
                ap_safe_name = filter_to_ascii(album_name_str)
                new_album_obj = {
                    "name": filter_to_ascii(ap_safe_name),
                    "uri": album.uri,
                    "tracks": [],
                }
                for track in album.tracks:  # track is GenericTrack
                    track_name_str = f"[{track.artist}] [{album.title}] [{track.title}]"
                    ap_safe_track_name = filter_to_ascii(track_name_str)
                    new_track_obj = {
                        "title": filter_to_ascii(ap_safe_track_name),
                        "uri": track.uri,
                        "artist": track.artist,
                    }
                    new_album_obj["tracks"].append(new_track_obj)
                apworld_content.append(new_album_obj)

            # 2. Get the backend config data
            backend_info = {"name": app.backend.service_name, "data": app.backend.get_client_data()}

            # 3. Check if we need to build and add the "display_data" key
            display_data_list = None  # Default to None
            if app.backend.client_requires_display_data():
                Logger.info("Generate: Backend requires display_data. Serializing...")
                display_data_list = []
                for album in effective_data:
                    album_dict = dataclasses.asdict(album)
                    if "display_image_url" in album_dict:
                        del album_dict["display_image_url"]
                    display_data_list.append(album_dict)
            else:
                Logger.info("Generate: Backend does not require display_data. Skipping.")

            # 5. Build the new top-level JSON structure
            final_json_data = {
                "backend": backend_info,
                "apworld": apworld_content,
                "display_data": display_data_list,  # <-- NEW KEY
            }

            # 6. Save the new structure
            json_filename = os.path.basename(output_dir) + ".json"
            json_parent_dir = os.path.dirname(output_dir)
            json_output_path = os.path.join(json_parent_dir, json_filename)

            with open(json_output_path, "w", encoding="utf-8") as f:
                json.dump(final_json_data, f, indent=4)

            # Copy 'docs' folder
            docs_src = os.path.join(template_dir, "docs")
            docs_dest = os.path.join(output_dir, "docs")
            if os.path.exists(docs_src) and os.path.isdir(docs_src):
                shutil.copytree(docs_src, docs_dest, dirs_exist_ok=True)

            # Create .apworld zip
            zip_filename = f"{os.path.basename(output_dir)}.apworld"
            parent_dir = os.path.dirname(output_dir)
            zip_path = os.path.join(parent_dir, zip_filename)

            Logger.info(f"Generate: creating .apworld archive at {zip_path}...")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zipf:
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, start=parent_dir)
                        zipf.write(file_path, arcname)

            Logger.info("Generate: .apworld file created successfully.")

            # Write a ready-to-edit starter YAML next to the artifacts.
            yaml_path = os.path.join(parent_dir, f"{os.path.basename(output_dir)}.yaml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                f.write(build_starter_yaml(apworld_name))

            Clock.schedule_once(
                lambda dt: setattr(
                    app.root, "status_text", f"Generated '{apworld_name}' → {parent_dir}"
                )
            )
            Clock.schedule_once(
                lambda dt: self._show_results(
                    parent_dir, zip_filename, json_filename, os.path.basename(yaml_path)
                )
            )

        except Exception as e:
            Clock.schedule_once(
                lambda dt: setattr(app.root, "status_text", "Generation failed. Check logs.")
            )
            Logger.error(f"Generate: Failed during file processing: {e}")

    def _show_results(self, folder, apworld_name, json_name, yaml_name):
        """Post-generation dialog: where the files are + the seed command (copyable)."""
        app = App.get_running_app()
        # Locate the shipped, cross-platform seed helper (repo root / tools).
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tool = os.path.join(repo_root, "tools", "make_seed.py")
        apworld_full = os.path.join(folder, apworld_name)
        ap_dir = app._load_gen_setting("ap_dir")
        cmd = f'"{sys.executable}" "{tool}" "{apworld_full}"'
        cmd += f' --ap-dir "{ap_dir}"' if ap_dir else "   # add --ap-dir, or set it in Settings"

        panel = BoxLayout(orientation="vertical", spacing="10dp", padding="10dp")
        body = Label(
            markup=True,
            halign="left",
            valign="top",
            text=(
                "[b]Generated![/b]  Saved to:\n"
                f"{folder}\n\n"
                f"• [b]{apworld_name}[/b] — the world\n"
                f"• [b]{json_name}[/b] — the catalog you load in the client\n"
                f"• [b]{yaml_name}[/b] — a starter YAML to edit\n\n"
                "[b]Next — build a playable seed[/b] (Copy command, run in a terminal):\n"
                f"{cmd}\n\n"
                "then host it (MultiServer) and connect the client with the catalog."
            ),
        )
        body.bind(size=lambda lbl, *_: setattr(lbl, "text_size", lbl.size))
        panel.add_widget(body)

        row = BoxLayout(size_hint_y=None, height="44dp", spacing="10dp")
        copy_btn = Button(text="Copy command")
        copy_btn.bind(
            on_release=lambda *_: (
                Clipboard.copy(cmd),
                setattr(app.root, "status_text", "Seed command copied to clipboard."),
            )
        )
        open_btn = Button(text="Open folder")
        open_btn.bind(on_release=lambda *_: _open_path(folder))
        close_btn = Button(text="Close")
        row.add_widget(copy_btn)
        row.add_widget(open_btn)
        row.add_widget(close_btn)
        panel.add_widget(row)

        popup = Popup(title="APWorld generated", content=panel, size_hint=(0.85, 0.6))
        close_btn.bind(on_release=popup.dismiss)
        popup.open()


class ItemMenu(DropDown):
    caller = ObjectProperty(None)

    def on_option_select(self, option_text):
        if self.caller:
            self.caller.menu_action(option_text)
        self.dismiss()


class CustomListItem(BoxLayout):
    # --- Visual Properties (for KV) ---
    text_line_1 = StringProperty("Line 1")
    text_line_2 = StringProperty("Line 2")
    text_line_3 = StringProperty("Line 3")
    text_line_4 = StringProperty("Line 4")
    image_source = StringProperty(KIVY_ICON)

    # --- Data Properties (set from search) ---
    list_id = StringProperty("")
    generic_item = ObjectProperty(
        None, allownone=True
    )  # This holds the GenericAlbum/Artist/Playlist

    # --- Derived action affordances (the kv binds a visible button to these) ---
    primary_label = StringProperty("")  # text of the row's main action button
    has_secondary = BooleanProperty(False)  # show the compact "..." menu (artists only)

    def on_list_id(self, *_):
        self._refresh_actions()

    def on_generic_item(self, *_):
        self._refresh_actions()

    def _refresh_actions(self):
        """Recompute the visible action button + whether a secondary menu exists.
        Driven by list_id + item type so every dict builder gets it for free, and
        recycled RecycleView rows can't show a stale label."""
        lid, item = self.list_id, self.generic_item
        if lid == "load_more_button":
            self.primary_label, self.has_secondary = "Load more", False
        elif lid == "apworld":
            # Multi-track albums: primary = Edit tracks, Remove in the "..." menu.
            # Single-track: nothing to edit, so primary = Remove.
            full = getattr(item, "_all_tracks", None) or getattr(item, "tracks", [])
            if len(full) > 1:
                self.primary_label, self.has_secondary = "Edit", True
            else:
                self.primary_label, self.has_secondary = "Remove", False
        elif lid == "search":
            if isinstance(item, GenericArtist):
                # primary = browse the artist's albums; secondary = add them all
                self.primary_label, self.has_secondary = "Albums", True
            else:
                self.primary_label, self.has_secondary = "+ Add", False
        elif lid:
            # Plugin-provided action rows (e.g. local_files 'Create New Album').
            # Give them a working button; on_primary routes to the plugin hook.
            self.primary_label, self.has_secondary = "Open", False
        else:
            self.primary_label, self.has_secondary = "", False

    def on_primary(self):
        """Handle the visible action button. Reuses the existing menu_action paths."""
        app = App.get_running_app()
        if self.list_id == "load_more_button":
            app.root.load_next_page()
            return
        if self.list_id == "apworld":
            # Multi-track row: primary button edits tracks (Remove is in the menu).
            if self.has_secondary:
                app.root.ids.list_container.edit_album_tracks(self.generic_item)
            else:
                self.menu_action("Remove")
            return
        if self.list_id == "search":
            if isinstance(self.generic_item, GenericArtist):
                self.menu_action("Show all albums")
            else:
                self.menu_action("Add to APWorld")
            return
        # Plugin-provided rows: route through the same hook the old "..." used.
        if app.plugin_host_ui and app.plugin_host_ui.on_item_menu_click(
            self.list_id, self.generic_item
        ):
            return

    def open_menu(self, button_widget):
        app = App.get_running_app()

        # --- NEW PLUGIN HOOK ---
        if app.plugin_host_ui:
            # Ask the plugin if it wants to handle this click directly
            was_handled = app.plugin_host_ui.on_item_menu_click(self.list_id, self.generic_item)
            if was_handled:
                return  # The plugin did something, so don't open a menu
        # --- END NEW HOOK ---

        if self.list_id == "load_more_button":
            # Directly trigger the next page load
            App.get_running_app().root.load_next_page()
            return

        menu = ItemMenu(caller=self)
        menu.auto_width = False
        button_added = False

        item_type = ""
        if isinstance(self.generic_item, GenericAlbum):
            item_type = "album"
        elif isinstance(self.generic_item, GenericArtist):
            item_type = "artist"
        elif isinstance(self.generic_item, GenericPlaylist):
            item_type = "playlist"

        if self.list_id == "search":
            # ... (this logic is unchanged)
            if item_type == "album" or item_type == "playlist":
                btn = Button(
                    text="Add to APWorld",
                    size_hint_y=None,
                    height="44dp",
                    on_release=lambda x: menu.on_option_select("Add to APWorld"),
                )
                menu.add_widget(btn)
                button_added = True
            elif item_type == "artist":
                btn1 = Button(
                    text="Add all artist albums",
                    size_hint_y=None,
                    height="44dp",
                    on_release=lambda x: menu.on_option_select("Add all artist albums"),
                )
                menu.add_widget(btn1)
                btn2 = Button(
                    text="Show all albums",
                    size_hint_y=None,
                    height="44dp",
                    on_release=lambda x: menu.on_option_select("Show all albums"),
                )
                menu.add_widget(btn2)
                button_added = True

        elif self.list_id == "apworld":
            # ... (this logic is unchanged)
            btn = Button(
                text="Remove from APWorld",
                size_hint_y=None,
                height="44dp",
                on_release=lambda x: menu.on_option_select("Remove"),
            )
            menu.add_widget(btn)
            button_added = True

        if button_added:
            menu.open(button_widget)
        else:
            app.root.status_text = f"No actions available for '{self.text_line_1}'"

    def menu_action(self, text):
        app = App.get_running_app()
        app.root.status_text = f"Action: {text} on {self.text_line_1}"

        if text == "Add to APWorld":
            app.root.status_text = f"Adding '{self.text_line_1}' to APWorld..."
            # Run the correct backend fetch in a thread
            if isinstance(self.generic_item, GenericAlbum):
                threading.Thread(target=self._add_album_thread, args=(self.generic_item,)).start()
            elif isinstance(self.generic_item, GenericPlaylist):
                threading.Thread(
                    target=self._add_playlist_thread, args=(self.generic_item,)
                ).start()

        elif text == "Add all artist albums":
            app.root.status_text = f"Fetching albums for '{self.text_line_1}'..."
            threading.Thread(
                target=self._add_all_artist_albums_thread, args=(self.generic_item,)
            ).start()

        elif text == "Show all albums":
            app.root.status_text = f"Fetching albums for '{self.text_line_1}'..."
            threading.Thread(
                target=self._show_artist_albums_thread, args=(self.generic_item,)
            ).start()

        elif text == "Remove":
            app.root.status_text = f"Removing '{self.text_line_1}'..."
            app.root.ids.list_container.remove_apworld_item(self.generic_item.uri)

    # --- Threaded Backend Calls ---
    def _add_album_thread(self, album: GenericAlbum):
        app = App.get_running_app()
        try:
            # Call the backend to get the album with its tracks
            populated_album = app.backend.get_album_with_tracks(album)
            Clock.schedule_once(lambda dt: self._add_data_to_apworld_list(populated_album))
        except Exception as e:
            Logger.error(f"APWorld: Failed to get tracks for {album.uri}: {e}")
            Clock.schedule_once(
                lambda dt: setattr(app.root, "status_text", f"Failed to add '{album.title}'")
            )

    def _add_playlist_thread(self, playlist: GenericPlaylist):
        app = App.get_running_app()
        try:
            # Call the backend to get playlist tracks (returns a GenericAlbum-like object)
            populated_item = app.backend.get_playlist_with_tracks(playlist)
            Clock.schedule_once(lambda dt: self._add_data_to_apworld_list(populated_item))
        except Exception as e:
            Logger.error(f"APWorld: Failed to get playlist {playlist.uri}: {e}")
            Clock.schedule_once(
                lambda dt: setattr(app.root, "status_text", f"Failed to add '{playlist.name}'")
            )

    def _add_all_artist_albums_thread(self, artist: GenericArtist):
        app = App.get_running_app()
        try:
            Clock.schedule_once(
                lambda dt: setattr(
                    app.root, "status_text", f"Finding albums for '{artist.name}'..."
                )
            )

            # This backend call returns a list of *fully populated* GenericAlbum objects
            all_populated_albums = app.backend.get_all_artist_albums(artist)

            Clock.schedule_once(
                lambda dt: setattr(
                    app.root,
                    "status_text",
                    f"Found {len(all_populated_albums)} albums. Adding to list...",
                )
            )

            for album in all_populated_albums:
                Clock.schedule_once(lambda dt, a=album: self._add_data_to_apworld_list(a))

            Clock.schedule_once(
                lambda dt: setattr(
                    app.root, "status_text", f"Finished adding albums for '{artist.name}'."
                )
            )
        except Exception as e:
            Logger.error(f"APWorld: Failed to get all albums for {artist.uri}: {e}")
            Clock.schedule_once(
                lambda dt: setattr(
                    app.root, "status_text", f"Failed to get albums for '{artist.name}'"
                )
            )

    def _show_artist_albums_thread(self, artist: GenericArtist):
        app = App.get_running_app()
        try:
            # This backend call returns a list of GenericAlbum objects (no tracks)
            albums_for_display = app.backend.get_artist_albums_for_display(artist)

            # We must convert these to the dict format the RecycleView expects
            new_display_data = []
            for item in albums_for_display:
                new_display_data.append(
                    {
                        "text_line_1": item.title,
                        "text_line_2": item.artist,
                        "text_line_3": f"{item.album_type} • Tracks: {item.total_tracks}",
                        "text_line_4": "",
                        "image_source": item.image_url or KIVY_ICON,
                        "list_id": "search",
                        "generic_item": item,  # Pass the object itself
                    }
                )

            def update_ui(dt):
                app.root.ids.list_container.list_one_data = new_display_data
                app.root.status_text = (
                    f"Showing {len(new_display_data)} albums for '{artist.name}'."
                )

            Clock.schedule_once(update_ui)

        except Exception as e:
            Logger.error(f"Failed to show albums for {artist.uri}: {e}")
            Clock.schedule_once(
                lambda dt: setattr(
                    app.root, "status_text", f"Failed to load albums for '{artist.name}'"
                )
            )

    def _add_data_to_apworld_list(self, album_data: GenericAlbum):
        """This is the final step, adding the populated data to the list."""
        app = App.get_running_app()
        list_container = app.root.ids.list_container

        # This will trigger the on_apworld_data binding
        list_container.add_apworld_item(album_data)


class TrackSelectionPopup(Popup):
    """
    Add-time per-track curation. Shows a checklist of an album's tracks so the
    user can uncheck bonus/live cuts before the album enters the APWorld list.

    Uses a plain ScrollView + BoxLayout (NOT a RecycleView) on purpose: checkbox
    state lives in the row widgets themselves, and RecycleView recycles those
    widgets, which would scramble the visible ticks on scroll. Track lists are
    small, so a non-recycling list is fine.
    """

    def __init__(self, album: GenericAlbum, on_resolve, tracks=None, selected_uris=None, **kwargs):
        super().__init__(**kwargs)
        self.album = album
        self.on_resolve = on_resolve  # called as on_resolve(album, states_or_None)
        # tracks to show (defaults to the album's current tracks); for editing, pass
        # the full list so removed tracks can be re-checked. selected_uris (None =
        # all) decides which start checked.
        self._tracks = tracks if tracks is not None else album.tracks
        self._selected_uris = selected_uris
        self._rows = []  # list of (CheckBox, GenericTrack)
        self.title = f"Select tracks — {album.title}"
        # ids aren't populated until the kv rule is applied; build on next frame.
        Clock.schedule_once(self._populate)

    def _populate(self, *_):
        box = self.ids.track_box
        box.clear_widgets()
        self._rows = []
        for track in self._tracks:
            checked = self._selected_uris is None or track.uri in self._selected_uris
            secs = max(0, int((track.duration_ms or 0) / 1000))
            duration = f"{secs // 60}:{secs % 60:02d}"
            label = f"{track.title}  ({duration})"
            # Full-row ToggleButton instead of a bare CheckBox: an [x]/[ ] prefix
            # reads clearly on the dark popup (where the checkbox glyph did not),
            # and the whole row is clickable.
            btn = ToggleButton(
                text=("[x]  " if checked else "[  ]  ") + label,
                state="down" if checked else "normal",
                size_hint_y=None,
                height=dp(36),
                halign="left",
                valign="middle",
            )
            btn.bind(size=lambda b, *_: setattr(b, "text_size", (b.width - dp(16), None)))
            btn.bind(
                state=lambda b, st, lbl=label: setattr(
                    b, "text", ("[x]  " if st == "down" else "[  ]  ") + lbl
                )
            )
            box.add_widget(btn)
            self._rows.append((btn, track))

    def on_ok(self):
        states = [btn.state == "down" for btn, _ in self._rows]
        album, resolve = self.album, self.on_resolve
        self.dismiss()
        resolve(album, states)

    def on_cancel(self):
        album, resolve = self.album, self.on_resolve
        self.dismiss()
        resolve(album, None)


class ListContainer(BoxLayout):
    list_one_data = ListProperty()  # Visual data for search list
    list_two_data = ListProperty()  # Visual data for APWorld list

    # This is the "source of truth" list, holding the full generic data
    apworld_data = ListProperty()  # List of GenericAlbum objects

    # Header text for the right-hand pane, e.g.
    # "Your APWorld — 5 albums · 73 tracks · 3h 52m · avg 3:24 · range 0:31–19:47".
    apworld_summary = StringProperty("Your APWorld — empty")

    # Second summary line (warning color) shown only when some tracks lack a probed
    # duration, e.g. "· 4 unknown lengths". Empty string collapses it in the kv.
    apworld_warn = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Per-track selection popups are shown one at a time, so that bulk adds
        # (e.g. "add all artist albums") don't stack N modals on top of each other.
        self._selection_queue = []
        self._selection_active = False

    def add_apworld_item(self, album_data: GenericAlbum, curate: bool = True):
        # Remember the full incoming track list once (before any add-time trim) so
        # the right-pane "Edit" can later re-add tracks non-destructively. Session
        # only — not serialized; GenericAlbum is a non-slots dataclass.
        if not getattr(album_data, "_all_tracks", None):
            album_data._all_tracks = list(album_data.tracks)

        # Check for duplicates against the committed list AND anything still
        # waiting in the track-selection queue.
        if any(item.uri == album_data.uri for item in self.apworld_data) or any(
            a.uri == album_data.uri for a in self._selection_queue
        ):
            Logger.info(f"APWorld: Item {album_data.title} already in list. Skipping.")
            App.get_running_app().root.status_text = f"'{album_data.title}' is already in the list."
            return

        # Bulk/whole-album adds (curate=False) and single-track albums have nothing
        # to curate; add directly without the per-track selection popup.
        if not curate or len(album_data.tracks) <= 1:
            self._finalize_add(album_data)
            return

        # Otherwise queue a per-track selection popup.
        self._selection_queue.append(album_data)
        if not self._selection_active:
            self._show_next_selection()

    def _show_next_selection(self):
        if not self._selection_queue:
            self._selection_active = False
            return
        self._selection_active = True
        album = self._selection_queue.pop(0)
        TrackSelectionPopup(album=album, on_resolve=self._on_selection_resolve).open()

    def _on_selection_resolve(self, album: GenericAlbum, states):
        # states is None on cancel; otherwise a list of per-track booleans.
        if states is not None:
            selected = [t for t, checked in zip(album.tracks, states) if checked]
            if selected:  # unchecking everything is treated as a cancel
                album.tracks = selected
                album.total_tracks = len(selected)
                self._finalize_add(album)
        # Advance the queue regardless of OK/cancel.
        self._show_next_selection()

    def _finalize_add(self, album_data: GenericAlbum):
        # Final dedup guard: an album popped into an in-flight selection popup is
        # in neither apworld_data nor the queue, so re-check by uri here before
        # committing to avoid duplicate location IDs in the generated world.
        if any(item.uri == album_data.uri for item in self.apworld_data):
            Logger.info(f"APWorld: Item {album_data.title} already in list. Skipping.")
            App.get_running_app().root.status_text = f"'{album_data.title}' is already in the list."
            return
        # This append() triggers on_apworld_data
        self.apworld_data.append(album_data)
        App.get_running_app().root.status_text = f"Added '{album_data.title}' to APWorld."

    def remove_apworld_item(self, item_uri):
        item_to_remove = next((item for item in self.apworld_data if item.uri == item_uri), None)

        if item_to_remove:
            self.apworld_data.remove(item_to_remove)  # This triggers on_apworld_data
            Logger.info(f"APWorld: Removed '{item_to_remove.title}'.")
            App.get_running_app().root.status_text = f"Removed '{item_to_remove.title}'."
        else:
            Logger.warning(f"APWorld: Could not find item to remove with URI: {item_uri}")

    def on_apworld_data(self, instance, new_data_list: list[GenericAlbum]):
        """Fires when apworld_data changes — rebuild the right-side visual list."""
        self.refresh_apworld_view()

    def refresh_apworld_view(self):
        """Rebuild the *visual* list (list_two_data) + header from apworld_data.
        Called by the on_apworld_data binding and after an in-place track edit
        (which doesn't change the list identity, so the binding won't fire)."""
        Logger.info("APWorld: Rebuilding right-side visual list.")
        visual_list = []
        for album in self.apworld_data:
            n = len(album.tracks)
            mins = sum(t.duration_ms or 0 for t in album.tracks) // 60000
            visual_list.append(
                {
                    "text_line_1": album.title,
                    "text_line_2": album.artist,
                    "text_line_3": f"{album.album_type} • {n} tracks",
                    "text_line_4": f"~{mins} min" if mins else "",
                    "image_source": album.display_image_url or album.image_url or KIVY_ICON,
                    "list_id": "apworld",
                    "generic_item": album,  # Pass the object itself for the 'Remove'/'Edit' action
                }
            )
        self.list_two_data = visual_list

        # Update the right-pane header summary + warn line from the pure corpus stats.
        s = corpus_stats(self.apworld_data)
        n_albums = s["n_albums"]
        if not n_albums:
            self.apworld_summary = "Your APWorld — empty"
            self.apworld_warn = ""
            return
        n_tracks = s["n_tracks"]
        summary = (
            f"Your APWorld — {n_albums} album{'s' if n_albums != 1 else ''} "
            f"· {n_tracks} track{'s' if n_tracks != 1 else ''}"
        )
        if s["total_ms"]:  # at least one known duration
            summary += (
                f" · {format_hm(s['total_ms'])}"
                f" · avg {format_hms(s['mean_ms'])}"
                f" · range {format_hms(s['min_ms'])}–{format_hms(s['max_ms'])}"
            )
        self.apworld_summary = summary
        n_unknown = s["n_unknown"]
        self.apworld_warn = (
            f"· {n_unknown} unknown length{'s' if n_unknown != 1 else ''}" if n_unknown else ""
        )

    def edit_album_tracks(self, album: GenericAlbum):
        """Open the track checklist for an already-added album. Non-lossy: shows the
        full original track list with the currently-included ones checked."""
        all_tracks = getattr(album, "_all_tracks", None) or album.tracks
        selected = {t.uri for t in album.tracks}
        TrackSelectionPopup(
            album=album, on_resolve=self._apply_edit, tracks=all_tracks, selected_uris=selected
        ).open()

    def _apply_edit(self, album: GenericAlbum, states):
        # states is None on cancel; otherwise per-track booleans aligned to _all_tracks.
        if states is None:
            return
        all_tracks = getattr(album, "_all_tracks", None) or album.tracks
        selected = [t for t, on in zip(all_tracks, states) if on]
        if not selected:  # unchecking everything is a no-op (use Remove instead)
            App.get_running_app().root.status_text = (
                "Keep at least one track (use Remove to drop the album)."
            )
            return
        album.tracks = selected
        album.total_tracks = len(selected)
        self.refresh_apworld_view()
        App.get_running_app().root.status_text = (
            f"Updated '{album.title}' — {len(selected)} tracks."
        )


class RootLayout(BoxLayout):
    status_text = StringProperty("App started. Ready.")
    current_search_query = ""
    current_search_type = ""
    current_search_offset = 0
    search_limit = 20

    def on_search_click(self, search_text, search_type):
        app = App.get_running_app()

        if app.backend and app.backend.is_authenticated:
            Logger.info(f"Search: Searching for '{search_text}' in '{search_type}'")
            self.status_text = f"Searching for '{search_text}'..."

            # Reset state
            self.current_search_query = search_text
            self.current_search_type = search_type
            self.current_search_offset = 0

            # Clear list
            self.ids.list_container.list_one_data = []

            # Start search at offset 0
            threading.Thread(target=self._search_thread, args=(search_text, search_type, 0)).start()
        else:
            # ... (error handling) ...
            pass

    def load_next_page(self):
        """Called when 'Load More' is clicked."""
        self.current_search_offset += self.search_limit
        self.status_text = (
            f"Loading page {int(self.current_search_offset / self.search_limit) + 1}..."
        )

        threading.Thread(
            target=self._search_thread,
            args=(self.current_search_query, self.current_search_type, self.current_search_offset),
        ).start()

    def _search_thread(self, search_text, search_type, offset):
        app = App.get_running_app()
        try:
            # Call backend with offset
            results = app.backend.search(
                search_text, search_type, limit=self.search_limit, offset=offset
            )

            Clock.schedule_once(lambda dt: self._update_search_list(results, search_type, offset))
        except Exception as e:
            Logger.error(f"Search failed: {e}")
            Clock.schedule_once(lambda dt: setattr(self, "status_text", "Search failed. See log."))

    def _update_search_list(self, results, search_type, offset):
        new_data = []

        # Convert results to UI dicts (Standard logic)
        for item in results:
            img = item.display_image_url or item.image_url or KIVY_ICON
            if isinstance(item, GenericArtist):
                new_data.append(
                    {
                        "text_line_1": item.name,
                        "text_line_2": f"Albums: {item.metadata.get('album_count', '?')}",
                        "text_line_3": f"Genres: {', '.join(item.metadata.get('genres', [])[:2])}",
                        "text_line_4": "",
                        "image_source": img,
                        "list_id": "search",
                        "generic_item": item,
                    }
                )
            elif isinstance(item, GenericAlbum):
                new_data.append(
                    {
                        "text_line_1": item.title,
                        "text_line_2": item.artist,
                        "text_line_3": f"{item.album_type} • Tracks: {item.total_tracks}",
                        "text_line_4": "",
                        "image_source": img,
                        "list_id": "search",
                        "generic_item": item,
                    }
                )
            elif isinstance(item, GenericPlaylist):
                new_data.append(
                    {
                        "text_line_1": item.name,
                        "text_line_2": f"Owner: {item.owner}",
                        "text_line_3": f"Tracks: {item.total_tracks}",
                        "text_line_4": "",
                        "image_source": img,
                        "list_id": "search",
                        "generic_item": item,
                    }
                )

        # --- MODIFIED PAGINATION LOGIC ---

        # 2. Get current list
        current_list = list(self.ids.list_container.list_one_data)

        # 3. Remove old "Load More" button if present
        if current_list and current_list[-1]["list_id"] == "load_more_button":
            current_list.pop()

        # 4. Append new results
        current_list.extend(new_data)

        # 5. Append new "Load More" button if needed
        if len(results) >= self.search_limit:
            current_list.append(
                {
                    "text_line_1": "Load More Results...",
                    "text_line_2": "",
                    "text_line_3": "",
                    "text_line_4": "",
                    "image_source": KIVY_ICON,
                    "list_id": "load_more_button",
                    "generic_item": None,
                }
            )

        # 6. Update the data
        self.ids.list_container.list_one_data = current_list
        self.status_text = f"Loaded {len(new_data)} more items."

        # 7. Restore Scroll Position (The Fix)
        if offset > 0 and new_data:

            def scroll_fix(dt):
                rv = self.ids.list_container.ids.search_rv

                # Calculate heights
                # Items are 100dp + 10px spacing.
                # We use dp(110) as a close approximation.
                item_height = dp(110)

                items_added = len(new_data)
                height_added = items_added * item_height

                # Total scrollable area height (approximate)
                total_content_height = len(rv.data) * item_height
                scrollable_distance = max(1, total_content_height - rv.height)

                # We added items to the bottom, so we are currently at 0.0 (bottom).
                # We want to move UP by the height of the items we added.
                # target_y = height_added / scrollable_distance

                target_y = height_added / scrollable_distance

                # Clamp and apply
                rv.scroll_y = max(0.0, min(1.0, target_y))

            Clock.schedule_once(scroll_fix, 0.1)

    def on_settings_click(self):
        """Open the generator Settings popup: a live theme switch + an About/how-to
        section. Mirrors the client's settings panel (built in Python, persisted to
        the app JsonStore via App.apply_theme)."""
        Logger.debug("Settings button clicked.")
        app = App.get_running_app()

        panel = BoxLayout(orientation="vertical", spacing="10dp", padding="10dp")

        # Theme switch (Dark/Light) — applies live and persists.
        is_light = app.theme_name == "light"
        theme_btn = ToggleButton(
            text=f"Theme: {'Light' if is_light else 'Dark'}",
            state="down" if is_light else "normal",
            size_hint_y=None,
            height="48dp",
        )

        def _on_theme_toggle(btn):
            name = "light" if btn.state == "down" else "dark"
            btn.text = f"Theme: {name.capitalize()}"
            app.apply_theme(name)

        theme_btn.bind(on_release=_on_theme_toggle)
        panel.add_widget(theme_btn)

        # About / how-to.
        about = Label(
            text=(
                "[b]Musipelago APWorld Generator[/b]\n\n"
                "How to use:\n"
                "1. Search for an album or artist above.\n"
                "2. Click [b]+ Add[/b] on results to add them to your APWorld.\n"
                "3. Click [b]Generate[/b] to build the .apworld + catalog.\n\n"
                "Tip: enable the Mixtape randomizer in the Generate dialog to shuffle "
                "tracks into custom packs."
            ),
            markup=True,
            halign="left",
            valign="top",
        )
        about.bind(size=lambda lbl, *_: setattr(lbl, "text_size", lbl.size))
        panel.add_widget(about)

        # Output folder: where generated worlds are written (remembered).
        out_row = BoxLayout(size_hint_y=None, height="44dp", spacing="10dp")
        out_lbl = Label(
            text=f"Output: {app.output_root()}",
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="left",
        )
        out_lbl.bind(size=lambda lbl, *_: setattr(lbl, "text_size", lbl.size))

        def _change_output(*_):
            from musipelago.plugins.local_files_backend import DirectoryPickerPopup

            def _picked(path):
                if path and os.path.isdir(path):
                    app._save_gen_setting("output_dir", path)
                    out_lbl.text = f"Output: {path}"

            start = app.output_root()
            if not os.path.isdir(start):
                start = os.path.expanduser("~")
            DirectoryPickerPopup(initial_path=start, on_selection=_picked).open()

        change_btn = Button(text="Change…", size_hint_x=None, width="100dp")
        change_btn.bind(on_release=_change_output)
        out_row.add_widget(out_lbl)
        out_row.add_widget(change_btn)
        panel.add_widget(out_row)

        # Archipelago folder: used to build the copy-command for the seed helper.
        ap_row = BoxLayout(size_hint_y=None, height="44dp", spacing="10dp")
        ap_lbl = Label(
            text=f"Archipelago: {app._load_gen_setting('ap_dir') or '(not set)'}",
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="left",
        )
        ap_lbl.bind(size=lambda lbl, *_: setattr(lbl, "text_size", lbl.size))

        def _change_ap(*_):
            from musipelago.plugins.local_files_backend import DirectoryPickerPopup

            def _picked(path):
                if path and os.path.isdir(path):
                    app._save_gen_setting("ap_dir", path)
                    ap_lbl.text = f"Archipelago: {path}"

            start = app._load_gen_setting("ap_dir") or os.path.expanduser("~")
            if not os.path.isdir(start):
                start = os.path.expanduser("~")
            DirectoryPickerPopup(initial_path=start, on_selection=_picked).open()

        ap_change = Button(text="Change…", size_hint_x=None, width="100dp")
        ap_change.bind(on_release=_change_ap)
        ap_row.add_widget(ap_lbl)
        ap_row.add_widget(ap_change)
        panel.add_widget(ap_row)

        popup = Popup(title="Settings", content=panel, size_hint=(0.7, 0.7), auto_dismiss=True)

        # Recovery: return to service / folder selection (no more force-quit).
        switch_btn = Button(text="Switch service / folder…", size_hint_y=None, height="44dp")
        switch_btn.bind(on_release=lambda *_: self._switch_service(popup))
        panel.add_widget(switch_btn)

        close_btn = Button(text="Close", size_hint_y=None, height="44dp")
        close_btn.bind(on_release=popup.dismiss)
        panel.add_widget(close_btn)

        popup.open()

    def _switch_service(self, settings_popup):
        """Confirm (if work would be lost) then restart the login flow."""
        app = App.get_running_app()
        settings_popup.dismiss()

        has_work = bool(self.ids.list_container.apworld_data)
        if not has_work:
            app.restart_login()
            return

        box = BoxLayout(orientation="vertical", spacing="10dp", padding="10dp")
        box.add_widget(
            Label(text="Switching service will clear the albums you've added. Continue?")
        )
        row = BoxLayout(size_hint_y=None, height="44dp", spacing="10dp")
        confirm = Popup(title="Switch service?", content=box, size_hint=(0.6, 0.4))
        cancel_btn = Button(text="Cancel")
        cancel_btn.bind(on_release=confirm.dismiss)
        ok_btn = Button(text="Switch", background_color=(0.6, 0.25, 0.25, 1))
        ok_btn.bind(on_release=lambda *_: (confirm.dismiss(), app.restart_login()))
        row.add_widget(cancel_btn)
        row.add_widget(ok_btn)
        box.add_widget(row)
        confirm.open()

    def on_generate_click(self):
        apworld_data = self.ids.list_container.apworld_data

        if not apworld_data:
            self.status_text = "APWorld list is empty. Nothing to generate."
            Logger.info("Generate: APWorld list is empty.")
            return

        # Open the popup and pass it the *generic data*
        popup = GeneratePopup(apworld_data=apworld_data)
        popup.open()


class MusipelagoAPWGenApp(App):
    plugin_host_ui = ObjectProperty(None)

    # Theme colors — the kv binds to app.col_*; apply_theme() swaps the palette.
    theme_name = StringProperty("dark")
    col_bg = ColorProperty(theme.DARK["bg"])
    col_surface = ColorProperty(theme.DARK["surface"])
    col_card = ColorProperty(theme.DARK["card"])
    col_accent = ColorProperty(theme.DARK["accent"])
    col_text = ColorProperty(theme.DARK["text"])
    col_text_dim = ColorProperty(theme.DARK["text_dim"])
    col_border = ColorProperty(theme.DARK["border"])
    col_warn = ColorProperty(theme.DARK["warn"])

    def build(self):
        self.backend = None
        self.login_popup = None
        resource_add_path(resource_path(""))
        self.icon = resource_path(os.path.join("resources", "musipelago_icon.png"))

        if getattr(sys, "frozen", False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.abspath(os.path.dirname(__file__))

        store_path = os.path.join(base_path, "musipelago_gen.json")
        self.store = JsonStore(store_path)

        # Restore the saved theme (default dark) before building the UI.
        self.apply_theme(self._load_gen_setting("theme", "dark"), persist=False)

        # Check env vars before trying to init backend
        self.plugin_manager = PluginManager(plugin_dir=resource_path("plugins"))
        self.plugin_manager.discover_plugins()

        return RootLayout()

    def _load_gen_setting(self, key, default=None):
        """Read a single value from the persisted `gen_settings` block."""
        try:
            if self.store.exists("gen_settings"):
                return self.store.get("gen_settings").get(key, default)
        except Exception as e:
            Logger.warning(f"Settings: could not read '{key}': {e}")
        return default

    def output_root(self):
        """Folder where generated worlds are written (remembered; default ~/Musipelago)."""
        return self._load_gen_setting("output_dir", os.path.expanduser("~/Musipelago"))

    def _save_gen_setting(self, key, value):
        """Merge a single value into `gen_settings` (preserves the other keys)."""
        try:
            gen = self.store.get("gen_settings") if self.store.exists("gen_settings") else {}
            gen[key] = value
            self.store.put("gen_settings", **gen)
        except Exception as e:
            Logger.warning(f"Settings: could not save '{key}': {e}")

    def apply_theme(self, name, persist=True):
        """Swap the live color palette (and optionally persist the choice)."""
        name = str(name).lower()
        if name not in theme.PALETTES:
            name = "dark"
        pal = theme.get_palette(name)
        self.theme_name = name
        for key in theme.KEYS:
            setattr(self, f"col_{key}", pal[key])
        if persist:
            self._save_gen_setting("theme", name)

    def restart_login(self):
        """Tear down the current backend/session and return to service selection.
        The recovery path for a wrong service/folder choice (no more force-quit)."""
        Logger.info("Settings: switching service — resetting session.")
        self.backend = None
        self.plugin_host_ui = None

        # Clear both panes / the source-of-truth list.
        try:
            lc = self.root.ids.list_container
            lc.apworld_data = []
            lc.list_one_data = []
            lc.list_two_data = []
        except Exception as e:
            Logger.warning(f"Settings: could not clear lists: {e}")

        # Local Files hides the search inputs in setup_ui — restore them for the next backend.
        try:
            sc = self.root.ids.search_controls
            sc.disabled = False
            sc.opacity = 1
        except Exception as e:
            Logger.warning(f"Settings: could not restore search bar: {e}")

        self.root.status_text = "Select a music service."
        self.on_start()

    def on_start(self):
        self.login_popup = LoginPopup(app_instance=self)

        backend_names = self.plugin_manager.get_available_backends(app_type_key="generator_backend")

        if backend_names:
            # We can now show friendly names if we want
            friendly_names = []
            for name in backend_names:
                manifest = self.plugin_manager.get_plugin_manifest(name)
                friendly_names.append(manifest.get("name", name))

            self.login_popup.backend_spinner.values = friendly_names
            # Store the real module names, mapped from the friendly names
            self.login_popup.friendly_to_module_map = dict(zip(friendly_names, backend_names))

            # Pre-select the last-used service so a remembered folder is one click away.
            last_service = self._load_gen_setting("last_service")
            last_friendly = next(
                (f for f, m in zip(friendly_names, backend_names) if m == last_service), None
            )
            self.login_popup.backend_spinner.text = last_friendly or friendly_names[0]

            self.login_popup.status_label.text = "Please select a service."
        else:
            self.login_popup.status_label.text = (
                "Error: No generator plugins found in 'plugins' folder."
            )
            self.login_popup.login_button.disabled = True

        self.login_popup.open()

    def on_login_success(self, user_data):
        Window.restore()
        if self.login_popup:
            self.login_popup.dismiss()
            self.login_popup = None

        # --- MODIFIED: Use friendly name ---
        manifest = self.plugin_manager.get_plugin_manifest(self.backend.service_name)
        friendly_name = manifest.get("name", self.backend.service_name.capitalize())

        self.root.status_text = (
            f"Logged into {friendly_name} as: {user_data.get('display_name', 'Unknown')}"
        )
        # --- END MODIFY ---

        # Remember the chosen folder (Local Files) so the next launch pre-fills it,
        # and the service so the spinner pre-selects it.
        chosen_dir = getattr(self.backend, "root_directory", None)
        if chosen_dir:
            self._save_gen_setting("last_directory", chosen_dir)
        self._save_gen_setting("last_service", self.backend.service_name)

        if self.backend.user_agent:
            AsyncImageWithHeaders.set_http_headers({"User-Agent": self.backend.user_agent})

        Logger.info(f"Loading UI host for {self.backend.service_name}")

        # 1. Get the UI Host class
        UIHostClass = self.plugin_manager.get_plugin_component_class(
            self.backend.service_name, "generator_ui"
        )

        if not UIHostClass:
            Logger.error(f"FATAL: Plugin {self.backend.service_name} has no 'generator_ui' class!")
            self.root.status_text = "Error: Plugin UI failed to load."
            return

        # 2. Create an instance and initialize it
        self.plugin_host_ui = UIHostClass()
        self.plugin_host_ui.initialize(self.root, self.backend)
        # --- END NEW UI SETUP ---

    def on_login_failure(self, error_message):
        Window.restore()
        if self.login_popup:
            self.login_popup.status_label.text = f"Auth Failed!\n{error_message}"
            self.login_popup.login_button.disabled = False
        else:
            Logger.error(f"Login: Failure: {error_message}")
            self.root.status_text = f"Auth Failed: {error_message}"
            self.on_start()

            def update_popup_status(dt):
                if self.login_popup:
                    self.login_popup.status_label.text = f"Auth Failed!\n{error_message}"
                    self.login_popup.login_button.disabled = False

            Clock.schedule_once(update_popup_status, 0)


def main():
    MusipelagoAPWGenApp().run()


if __name__ == "__main__":
    main()
