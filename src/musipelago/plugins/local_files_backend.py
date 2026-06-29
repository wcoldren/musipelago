import base64
import hashlib
import os
import random
import re
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.logger import Logger
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

# --- Mutagen import for ID3 tags ---
try:
    import mutagen
    from mutagen import File as MutagenFile
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import ID3
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    from mutagen.oggvorbis import OggVorbis
except ImportError:
    Logger.warning("LocalFilesBackend: 'mutagen' not installed.")
    mutagen = None
    MutagenFile = None

# --- Imports from the main application's interface ---
from musipelago.backends import (
    AbstractClientHost,
    AbstractMusicBackend,
    AbstractPluginHost,
    GenericAlbum,
    GenericArtist,
    GenericPlaylist,
    GenericTrack,
)
from musipelago.client_ui_components import GenericPlaybackInfo, ItemMenu
from musipelago.utils import (
    KIVY_ICON,
    build_cover_collage,
    collect_source_covers,
    find_cover_in_dir,
)
from musipelago.utils_client import (
    build_continuation_queue,
    eligible_shuffle_tracks,
    pick_shuffle_tracks,
    seek_trap_target,
)


def parse_track_no(raw):
    """Parse a tag track/disc number to an int, or None. Handles '5', '05',
    '5/12', '', None. Pure — unit-testable."""
    if raw is None:
        return None
    s = str(raw).split("/", 1)[0].strip()
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _leading_num(filename):
    """Leading integer of a filename (e.g. '03. Foo.mp3' -> 3), or None."""
    m = re.match(r"\s*(\d+)", filename)
    return int(m.group(1)) if m else None


def sort_track_infos(items):
    """Order scanned tracks. Each item is (filename, track_no, disc_no, info);
    returns the info payloads in album order. Pure — unit-testable.

    Heuristic (folder-level, picks the most reliable signal):
      1. Numbered filenames ('01.', '02.' …, common + authoritative even when tags
         are messy — e.g. reissues whose tracknumber tags restart per bonus set).
      2. Otherwise unique tag (disc, track) numbers.
      3. Otherwise plain filename order.
    """
    n = len(items)
    if n == 0:
        return []
    leads = [_leading_num(it[0]) for it in items]
    track_keys = [(it[2] or 0, it[1]) for it in items]
    use_lead = all(x is not None for x in leads)
    use_track = (
        (not use_lead) and all(it[1] is not None for it in items) and len(set(track_keys)) == n
    )

    def key(i):
        fn = items[i][0].lower()
        if use_lead:
            return (leads[i], fn)
        if use_track:
            return (items[i][2] or 0, items[i][1], fn)
        return (0, 0, fn)

    return [items[i][3] for i in sorted(range(n), key=key)]


# --- Plugin-specific helper UI ---


class DirectoryPickerPopup(Popup):
    """
    A pure Kivy popup that lets the user select a directory.
    Replaces the need for tkinter or inconsistent plyer behavior.
    """

    def __init__(self, initial_path, on_selection, multiselect=False, **kwargs):
        super().__init__(**kwargs)
        self.title = "Select Album Folder(s)" if multiselect else "Select Album Directory"
        self.size_hint = (0.9, 0.9)
        self.on_selection = on_selection
        self.multiselect = multiselect

        layout = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))

        if multiselect:
            layout.add_widget(
                Label(
                    text="Tip: Ctrl/Cmd-click (or Shift-click) to pick several album folders.",
                    size_hint_y=None,
                    height=dp(24),
                )
            )

        # 1. File Chooser (List View)
        self.file_chooser = FileChooserListView(
            path=initial_path,
            dirselect=True,  # CRITICAL: Allow directory selection
            multiselect=multiselect,
            filters=[""],  # Show directories only (mostly)
        )
        layout.add_widget(self.file_chooser)

        # 2. Buttons
        btn_layout = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))

        cancel_btn = Button(text="Cancel", on_release=self.dismiss)
        select_btn = Button(
            text="Import Selected" if multiselect else "Select This Folder",
            on_release=self.select_current,
        )

        btn_layout.add_widget(cancel_btn)
        btn_layout.add_widget(select_btn)

        layout.add_widget(btn_layout)
        self.content = layout

    def select_current(self, *args):
        # Selected entries, falling back to the currently open folder.
        selection = list(self.file_chooser.selection) or [self.file_chooser.path]
        self.dismiss()
        if self.multiselect:
            self.on_selection(selection)  # caller gets a list
        else:
            self.on_selection(selection[0])  # caller gets a single path


class MultiFolderPopup(Popup):
    """Pick one or more album subfolders to import via an explicit checklist.

    Replaces FileChooser modifier-click multiselect (Ctrl/Cmd is unreliable +
    platform-specific). Lists the immediate subfolders of a parent dir as
    [x]/[ ] toggle rows; OK returns the checked paths as a list.
    """

    def __init__(self, start_dir, on_resolve, **kwargs):
        super().__init__(**kwargs)
        self.title = "Import album folders"
        self.size_hint = (0.9, 0.9)
        self.on_resolve = on_resolve
        self.current = (
            start_dir if (start_dir and os.path.isdir(start_dir)) else os.path.expanduser("~")
        )
        self._rows = []

        root = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))

        top = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self.path_lbl = Label(halign="left", valign="middle", shorten=True, shorten_from="left")
        self.path_lbl.bind(size=lambda l, *_: setattr(l, "text_size", l.size))
        change_btn = Button(text="Change folder…", size_hint_x=None, width=dp(140))
        change_btn.bind(on_release=self._change_folder)
        top.add_widget(self.path_lbl)
        top.add_widget(change_btn)
        root.add_widget(top)

        sel = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(8))
        all_btn = Button(text="Select all")
        all_btn.bind(on_release=lambda *_: self._set_all("down"))
        none_btn = Button(text="Select none")
        none_btn.bind(on_release=lambda *_: self._set_all("normal"))
        sel.add_widget(all_btn)
        sel.add_widget(none_btn)
        root.add_widget(sel)

        scroll = ScrollView(do_scroll_x=False)
        self.box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2))
        self.box.bind(minimum_height=self.box.setter("height"))
        scroll.add_widget(self.box)
        root.add_widget(scroll)

        btns = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        cancel_btn = Button(text="Cancel")
        cancel_btn.bind(on_release=self._cancel)
        import_btn = Button(text="Import checked")
        import_btn.bind(on_release=self._import)
        btns.add_widget(cancel_btn)
        btns.add_widget(import_btn)
        root.add_widget(btns)

        self.content = root
        Clock.schedule_once(lambda dt: self._populate())

    def _populate(self):
        self.path_lbl.text = f"Folder: {self.current}"
        self.box.clear_widgets()
        self._rows = []
        try:
            subs = sorted(
                n for n in os.listdir(self.current) if os.path.isdir(os.path.join(self.current, n))
            )
        except OSError:
            subs = []
        if not subs:
            self.box.add_widget(
                Label(
                    text="(no subfolders here — use Change folder…)",
                    size_hint_y=None,
                    height=dp(36),
                )
            )
            return
        for name in subs:
            path = os.path.join(self.current, name)
            btn = ToggleButton(
                text=f"[x]  {name}",
                state="down",
                size_hint_y=None,
                height=dp(36),
                halign="left",
                valign="middle",
            )
            btn.bind(size=lambda b, *_: setattr(b, "text_size", (b.width - dp(16), None)))
            btn.bind(
                state=lambda b, st, n=name: setattr(
                    b, "text", ("[x]  " if st == "down" else "[  ]  ") + n
                )
            )
            self.box.add_widget(btn)
            self._rows.append((btn, path))

    def _set_all(self, state):
        for btn, _ in self._rows:
            btn.state = state

    def _change_folder(self, *_):
        def _picked(path):
            if path and os.path.isdir(path):
                self.current = path
                self._populate()

        DirectoryPickerPopup(initial_path=self.current, on_selection=_picked).open()

    def _import(self, *_):
        selected = [path for btn, path in self._rows if btn.state == "down"]
        self.dismiss()
        self.on_resolve(selected)

    def _cancel(self, *_):
        self.dismiss()
        self.on_resolve(None)


class CreateAlbumPopup(Popup):
    """
    A plugin-specific popup for creating a new local album.
    """

    def __init__(self, title, artist, on_create_callback, **kwargs):
        super().__init__(**kwargs)
        self.title = "Import album"
        self.size_hint = (0.8, None)
        self.auto_dismiss = False

        self.on_create_callback = on_create_callback

        layout = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        form_grid = GridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(88))

        form_grid.add_widget(Label(text="Album Title:", size_hint_x=0.3))
        self.album_input = TextInput(text=title, multiline=False, write_tab=False)
        form_grid.add_widget(self.album_input)

        form_grid.add_widget(Label(text="Artist:", size_hint_x=0.3))
        self.artist_input = TextInput(text=artist, multiline=False, write_tab=False)
        form_grid.add_widget(self.artist_input)

        layout.add_widget(form_grid)

        button_layout = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        cancel_btn = Button(text="Cancel", on_release=self.dismiss)
        create_btn = Button(text="Create", on_release=self.on_create_press)
        button_layout.add_widget(cancel_btn)
        button_layout.add_widget(create_btn)

        layout.add_widget(button_layout)

        self.content = layout
        self.height = dp(220)

    def on_create_press(self, *args):
        album_title = self.album_input.text.strip()
        artist_name = self.artist_input.text.strip()

        if not album_title:
            self.album_input.text = ""
            return

        if not artist_name:
            artist_name = "Unknown Artist"

        self.on_create_callback(self, album_title, artist_name)


class LocalFilesLoginUI(BoxLayout):
    """
    This is the Kivy widget that the main app will show in a popup.
    """

    def __init__(self, initial_path=None, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.spacing = "10dp"
        self.padding = "10dp"

        # Set a fixed height for this widget so it doesn't collapse
        self.size_hint_y = None
        # Label (30) + TextInput (40) + Button (44) + Spacing (2*10) + Padding (2*10) = 154
        self.height = dp(154)
        self.desired_popup_height = dp(280)

        # Label
        self.add_widget(
            Label(
                text="Select your root music directory:",
                halign="left",
                size_hint_y=None,
                height=dp(30),
            )
        )

        # Text Input to display the path. Pre-filled from the catalog's root_directory
        # so the user can just click Login (the picker still lets them change it).
        self.path_input = TextInput(
            text=(initial_path if initial_path and os.path.isdir(initial_path) else ""),
            hint_text="No directory selected...",
            readonly=True,
            size_hint_y=None,
            height=dp(40),
        )
        self.add_widget(self.path_input)

        # Button to open the dialog
        self.choose_btn = Button(text="Choose Directory...", size_hint_y=None, height=dp(44))
        self.choose_btn.bind(on_release=self.open_dialog)
        self.add_widget(self.choose_btn)

    def open_dialog(self, *args):
        """
        Open a pure-Kivy directory chooser (no plyer/pyobjus). Mirrors the generator's
        DirectoryPickerPopup usage in LocalFilesHostUI.
        """
        start_path = self.path_input.text
        if not start_path or not os.path.isdir(start_path):
            start_path = os.path.expanduser("~")
        DirectoryPickerPopup(initial_path=start_path, on_selection=self._on_dir_selected).open()

    def _on_dir_selected(self, path):
        """Callback from DirectoryPickerPopup (passes a single path string)."""
        if path:
            self.path_input.text = path
            Logger.info(f"LocalFilesLoginUI: Path selected: {path}")


class LocalFilesBackendLogic(AbstractMusicBackend):
    """
    "Authentication" is just selecting a root music directory.
    """

    def __init__(self, service_name_key: str, on_login_success, on_login_failure):
        super().__init__(service_name_key, on_login_success, on_login_failure)
        self.root_directory = None

    def get_login_ui(self) -> object:
        """
        This is the "contract". We return a Kivy widget.
        """
        Logger.info("LocalFilesBackend: Providing custom login UI.")
        return LocalFilesLoginUI(initial_path=self.root_directory)

    def login(self, login_widget: object = None):
        """
        The main app calls this AFTER the user clicks "Login"
        on the custom popup.
        """
        if login_widget is None or not isinstance(login_widget, LocalFilesLoginUI):
            msg = "LocalFilesBackend: Login failed, custom UI was not provided."
            Logger.error(msg)
            Clock.schedule_once(lambda dt: self.on_login_failure(msg))
            return

        # 1. Extract the path from the UI widget
        directory_path = login_widget.path_input.text

        # 2. Check if a path was actually selected
        if not directory_path or not os.path.isdir(directory_path):
            msg = "No valid directory selected."
            Logger.warning(f"LocalFilesBackend: {msg}")
            Clock.schedule_once(lambda dt: self.on_login_failure(msg))
            return

        # 3. --- LOGIN SUCCESS ---
        self.root_directory = directory_path
        self.is_authenticated = True

        folder_name = os.path.basename(directory_path)
        user_data = {"display_name": f"Folder: ...{folder_name}"}

        Logger.info(f"LocalFilesBackend: 'Logged in' to {directory_path}")
        # Call success on the main thread
        Clock.schedule_once(lambda dt: self.on_login_success(user_data))

    # --- Abstract Method Stubs ---

    def search(self, query: str, search_type: str, limit: int = 20):
        Logger.info("LocalFilesBackend: Searching... (not implemented)")
        return []

    def get_album_with_tracks(self, album: GenericAlbum):
        return album

    def get_playlist_with_tracks(self, playlist: GenericPlaylist):
        return None

    def get_all_artist_albums(self, artist: GenericArtist):
        return []

    def get_artist_albums_for_display(self, artist: GenericArtist):
        return []

    def get_client_data(self) -> dict:
        """
        Pass the selected root music directory to the client.
        """
        return {"root_directory": self.root_directory}

    def initialize_client(self, client_data: dict, app: App):
        """
        Called by the client app *after* successful login.
        This just sets the root directory.
        """
        self.root_directory = client_data.get("root_directory")
        if not self.root_directory:
            Logger.error("LocalFilesClient: No 'root_directory' found in JSON data.")
            # This will fail gracefully
            app.on_login_failure("Invalid JSON: Missing root_directory")
            return

        Logger.info(f"LocalFilesClient: Initialized with root: {self.root_directory}")
        self.is_authenticated = True
        # No return value, no callback

    def client_requires_display_data(self) -> bool:
        """
        Local Files client relies *entirely* on the display_data
        block, as it has no API to call.
        """
        return True


class LocalFilesHostUI(AbstractPluginHost):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._temp_track_info = []
        self._temp_chosen_dir = ""

    def setup_ui(self):
        # ... (implementation unchanged)
        Logger.info("LocalFilesHostUI: Setting up custom 'Local Files' UI.")
        # Hide only the search inputs — keep the Settings button reachable so the
        # user can switch service / folder without force-quitting.
        self.root_layout.ids.search_controls.disabled = True
        self.root_layout.ids.search_controls.opacity = 0
        custom_ui_data = [
            {
                "text_line_1": "Import album(s)",
                "text_line_2": "Tick the album folders to import",
                "text_line_3": "",
                "text_line_4": "",
                "image_source": KIVY_ICON,
                "list_id": "local_files_action",
                "generic_item": "create_album_action",
            },
            {
                "text_line_1": "Scan Root Directory",
                "text_line_2": "Import every album folder in your library",
                "text_line_3": "",
                "text_line_4": "",
                "image_source": KIVY_ICON,
                "list_id": "local_files_action",
                "generic_item": "scan_dir_action",
            },
            # ... (other actions like 'scan_dir_action' can be added here) ...
        ]
        self.root_layout.ids.list_container.list_one_data = custom_ui_data

    def on_search_click(self, search_text, search_type):
        pass

    def on_item_menu_click(self, item_list_id: str, generic_item: any) -> bool:
        if item_list_id == "local_files_action":
            action_id = str(generic_item)

            if action_id == "create_album_action":
                self.start_create_album_flow()
                return True  # We handled the click

            elif action_id == "scan_dir_action":
                self.root_layout.status_text = "Scanning root directory for albums…"
                Logger.info("UI: 'Scan Root Directory' clicked.")
                threading.Thread(target=self._scan_root_thread).start()
                return True  # We handled the click

        return False

    # --- NEW ALBUM CREATION FLOW ---

    def start_create_album_flow(self):
        """
        Starts the process using our custom DirectoryPickerPopup.
        This respects 'initial_path' perfectly because it's pure Kivy.
        """
        # Determine start path
        start_path = self.backend.root_directory
        if not start_path or not os.path.isdir(start_path):
            start_path = os.path.expanduser("~")

        Logger.info(f"LocalFiles: Opening folder checklist at {start_path}")

        # Explicit checklist of subfolders (reliable cross-platform multiselect;
        # Ctrl/Cmd-click in the file chooser is flaky). One checked folder -> the
        # named confirm flow; several -> whole-album import.
        MultiFolderPopup(start_dir=start_path, on_resolve=self._on_dirs_selected).open()

    def _on_dirs_selected(self, paths):
        """Callback from the folder checklist (receives a list of folders)."""
        dirs = [p for p in (paths or []) if os.path.isdir(p)]
        if not dirs:
            self.root_layout.status_text = "Import cancelled (no folder selected)."
            return
        if len(dirs) == 1:
            # Single folder: keep the confirm dialog so you can name the album.
            self.root_layout.status_text = f"Scanning folder: {os.path.basename(dirs[0])}..."
            threading.Thread(target=self._scan_dir_thread, args=(dirs[0],)).start()
        else:
            self.root_layout.status_text = f"Importing {len(dirs)} folders..."
            threading.Thread(target=self._import_dirs_thread, args=(dirs,)).start()

    def _import_dirs_thread(self, dirs):
        """(THREAD) Import several album folders as whole albums (no confirm popups)."""
        if not mutagen:
            Clock.schedule_once(
                lambda dt: setattr(
                    self.root_layout, "status_text", "Error: 'mutagen' is not installed."
                )
            )
            return
        try:
            albums, total = [], 0
            for d in dirs:
                track_info, alb, art = self._scan_one_dir(d)
                if not track_info:
                    continue
                title = alb or os.path.basename(d)
                artist = art or "Unknown Artist"
                albums.append(self._build_album(track_info, title, artist, d))
                total += len(track_info)
            if not albums:
                Clock.schedule_once(
                    lambda dt: setattr(
                        self.root_layout,
                        "status_text",
                        "No supported audio found in the selected folders.",
                    )
                )
                return

            def _commit(dt):
                for album in albums:
                    self.add_to_apworld(album, curate=False)
                self.root_layout.status_text = f"Imported {len(albums)} albums ({total} tracks)."

            Clock.schedule_once(_commit)
        except Exception as e:
            err = str(e)
            Logger.error(f"LocalFiles: Failed to import folders: {err}")
            Clock.schedule_once(
                lambda dt: setattr(self.root_layout, "status_text", f"Error: {err}")
            )

    # ---------------------------------------

    # Audio extensions recognized by the scanner (shared by single + root scans).
    VALID_AUDIO_EXTS = (".mp3", ".flac", ".m4a", ".ogg", ".wma")

    def _scan_one_dir(self, chosen_dir: str):
        """Scan a single directory for audio files and read their tags.

        Returns ``(track_info_list, consensus_album, consensus_artist)`` where each
        track_info is ``(filepath, title_tag, artist_tag, duration_ms)``. Returns an
        empty list when the folder has no supported audio. Pure of UI — safe to call
        from a worker thread for one folder or many.
        """
        entries = []  # (sort_key, info_tuple)
        album_tags = []
        artist_tags = []

        for filename in os.listdir(chosen_dir):
            if not filename.lower().endswith(self.VALID_AUDIO_EXTS):
                continue

            filepath = os.path.join(chosen_dir, filename)
            title_tag = None
            artist_tag = None
            duration_ms = 0
            track_no = None
            disc_no = None

            try:
                # mutagen.File detects format from header/extension; easy=True
                # normalizes keys to 'title'/'artist'/'album' across formats.
                audio = MutagenFile(filepath, easy=True)
                if audio:
                    if "title" in audio:
                        title_tag = audio["title"][0]
                    if "artist" in audio:
                        artist_tag = audio["artist"][0]
                        artist_tags.append(artist_tag)
                    if "album" in audio:
                        album_tags.append(audio["album"][0])
                    if "tracknumber" in audio:
                        track_no = parse_track_no(audio["tracknumber"][0])
                    if "discnumber" in audio:
                        disc_no = parse_track_no(audio["discnumber"][0])
                    # audio.info.length is seconds across all mutagen types.
                    if audio.info and audio.info.length:
                        duration_ms = int(audio.info.length * 1000)
            except Exception as e:
                # Don't crash on one bad file; fall back to the filename later.
                Logger.warning(f"LocalFiles: Could not read metadata for {filename}: {e}")

            entries.append(
                (filename, track_no, disc_no, (filepath, title_tag, artist_tag, duration_ms))
            )

        track_info_list = sort_track_infos(entries)

        consensus_album = max(set(album_tags), key=album_tags.count) if album_tags else ""
        consensus_artist = max(set(artist_tags), key=artist_tags.count) if artist_tags else ""
        return track_info_list, consensus_album, consensus_artist

    def _scan_dir_thread(self, chosen_dir: str):
        """(THREAD) Scan one folder, then open the confirm popup (Create New Album)."""
        if not mutagen:
            Logger.error("Cannot scan: 'mutagen' is not installed.")
            Clock.schedule_once(
                lambda dt: setattr(
                    self.root_layout, "status_text", "Error: 'mutagen' is not installed."
                )
            )
            return

        try:
            track_info_list, consensus_album, consensus_artist = self._scan_one_dir(chosen_dir)

            if not track_info_list:
                Clock.schedule_once(
                    lambda dt: setattr(
                        self.root_layout,
                        "status_text",
                        f"No supported audio files found in '{os.path.basename(chosen_dir)}'.",
                    )
                )
                return

            self._temp_track_info = track_info_list
            self._temp_chosen_dir = chosen_dir

            Clock.schedule_once(
                lambda dt: self._open_create_album_popup(consensus_album, consensus_artist)
            )

        except Exception as e:
            err = str(e)
            Logger.error(f"LocalFiles: Failed to scan directory: {err}")
            Clock.schedule_once(
                lambda dt: setattr(self.root_layout, "status_text", f"Error: {err}")
            )

    def _scan_root_thread(self):
        """(THREAD) Scan every immediate subfolder of the root dir, importing each as
        a whole album (no per-track popups). Matches the user's "I picked the folder
        with all my albums in it" expectation."""
        if not mutagen:
            Logger.error("Cannot scan: 'mutagen' is not installed.")
            Clock.schedule_once(
                lambda dt: setattr(
                    self.root_layout, "status_text", "Error: 'mutagen' is not installed."
                )
            )
            return

        root_dir = self.backend.root_directory
        if not root_dir or not os.path.isdir(root_dir):
            Clock.schedule_once(
                lambda dt: setattr(self.root_layout, "status_text", "No valid root directory set.")
            )
            return

        try:
            albums = []
            total_tracks = 0
            for name in sorted(os.listdir(root_dir)):
                sub = os.path.join(root_dir, name)
                if not os.path.isdir(sub):
                    continue
                track_info, alb, art = self._scan_one_dir(sub)
                if not track_info:
                    continue
                title = alb or name  # fall back to the folder name
                artist = art or "Unknown Artist"
                albums.append(self._build_album(track_info, title, artist, sub))
                total_tracks += len(track_info)

            if not albums:
                Clock.schedule_once(
                    lambda dt: setattr(
                        self.root_layout,
                        "status_text",
                        f"No album folders found in '{os.path.basename(root_dir)}'.",
                    )
                )
                return

            def _commit(dt):
                for album in albums:
                    self.add_to_apworld(album, curate=False)  # whole albums, no popup
                self.root_layout.status_text = (
                    f"Imported {len(albums)} albums ({total_tracks} tracks)."
                )

            Clock.schedule_once(_commit)

        except Exception as e:
            err = str(e)
            Logger.error(f"LocalFiles: Failed to scan root: {err}")
            Clock.schedule_once(
                lambda dt: setattr(self.root_layout, "status_text", f"Error: {err}")
            )

    def _open_create_album_popup(self, consensus_album: str, consensus_artist: str):
        """
        (MAIN THREAD) Opens the new CreateAlbumPopup.
        """
        self.root_layout.status_text = (
            f"Found {len(self._temp_track_info)} tracks. Please confirm album details."
        )

        popup = CreateAlbumPopup(
            title=consensus_album,
            artist=consensus_artist,
            on_create_callback=self.on_album_popup_create,
        )
        popup.open()

    def _build_album(self, track_info, title: str, artist: str, source_dir: str) -> GenericAlbum:
        """Construct a GenericAlbum from scanned track info. URIs are stored relative
        to the backend root so the client can resolve them on the player's disk.
        Reused by single-folder create and the root scan."""
        root_dir = self.backend.root_directory
        album_uri = os.path.relpath(source_dir, root_dir).replace("\\", "/")

        generic_tracks = []
        for filepath, title_tag, artist_tag, duration_ms in track_info:
            track_title = title_tag or os.path.splitext(os.path.basename(filepath))[0]
            track_artist = artist_tag or artist
            track_uri = os.path.relpath(filepath, root_dir).replace("\\", "/")
            generic_tracks.append(
                GenericTrack(
                    uri=track_uri,
                    title=track_title,
                    artist=track_artist,
                    album_title=title,
                    duration_ms=duration_ms,
                    service="local",
                )
            )

        # Local cover (cover.jpg/folder.jpg/etc) for the gen-app row. display_image_url
        # is preferred by the rows and stripped from the saved catalog, so no absolute
        # path is persisted; the client re-derives art on its own at play time.
        return GenericAlbum(
            uri=album_uri,
            title=title,
            artist=artist,
            image_url="",
            total_tracks=len(generic_tracks),
            album_type="Album",
            service="local",
            tracks=generic_tracks,
            display_image_url=find_cover_in_dir(source_dir),
        )

    def on_album_popup_create(
        self, popup_instance: Popup, new_album_title: str, new_artist_name: str
    ):
        """
        (MAIN THREAD) Callback from the CreateAlbumPopup.
        This is where we finally create the GenericAlbum.
        """
        try:
            new_album = self._build_album(
                self._temp_track_info, new_album_title, new_artist_name, self._temp_chosen_dir
            )

            # Add to the APWorld (right pane) — single create still offers curation.
            self.add_to_apworld(new_album)

            self.root_layout.status_text = f"Added album '{new_album.title}'."

        except Exception as e:
            Logger.error(f"LocalFiles: Failed to create album: {e}")
            self.root_layout.status_text = "Error creating album. Check logs."

        finally:
            # Clean up temp data and close popup
            self._temp_track_info = []
            self._temp_chosen_dir = ""
            popup_instance.dismiss()


class LocalFilesClientHost(AbstractClientHost):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_playing_track_uri = None
        self.current_playing_track_title = None
        self.playback_queue = []
        self.queue_index = -1

        # Shuffle Trap state. _trap_playing is set while a forced replay is in progress so the
        # queue-finished branch restores prior playback instead of parking; _trap_saved holds
        # what to resume; _trap_pending serializes overlapping Shuffle Traps (one at a time).
        self._trap_playing = False
        self._trap_saved = None
        self._trap_pending = 0

        # UI References
        self.playback_ui = None
        self.track_label = None
        self.progress_bar = None
        self.poll_event = None

    def setup_ui(self):
        Logger.info("LocalFilesClientHost: Setting up UI.")

        # 1. Bind is_playing
        self.bind(is_playing=self.root_layout.setter("is_playing"))

        # 2. Instantiate and inject GenericPlaybackInfo
        self.playback_info_widget = self.root_layout.playback_info_widget = GenericPlaybackInfo()

        # Initialize with empty state
        self.playback_info_widget.track_title = "Not Playing"
        self.playback_info_widget.artist_album = "Select a track"
        self.playback_info_widget.current_time = "00:00"
        self.playback_info_widget.total_time = "00:00"
        self.playback_info_widget.progress_value = 0
        self.playback_info_widget.art_source = KIVY_ICON

        center_slot = self.root_layout.ids.playback_center
        center_slot.clear_widgets()
        center_slot.add_widget(self.playback_info_widget)

        self.root_layout.set_status("Local files loaded. Ready to play.")

    def fetch_game_data_threaded(self, game_data: dict):
        Logger.info("LocalFilesClientHost: Parsing and scanning local data...")
        display_data = game_data.get("display_data")
        if not display_data:
            Clock.schedule_once(
                lambda dt: self.root_layout.set_status("Error: JSON missing 'display_data' key.")
            )
            return

        threading.Thread(target=self._parse_thread_target, args=(display_data,)).start()

    def _parse_thread_target(self, display_data: list):
        """
        (THREAD) Parses JSON and scans filesystem for artwork.
        """
        root_dir = self.backend.root_directory
        cache_dir = os.path.join(self.app.user_data_dir, "image_cache")
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

        try:
            for album_dict in display_data:
                # 1. Reconstruct Tracks
                track_objects = []
                for track_dict in album_dict.get("tracks", []):
                    track_objects.append(GenericTrack(**track_dict))

                # 2. Resolve Album URI to Absolute Path
                album_uri = album_dict.get("uri")
                abs_album_path = os.path.normpath(os.path.join(root_dir, album_uri))

                # 3. --- NEW: SCAN FOR ARTWORK ---
                # We look for art now, while parsing the data.
                # This updates the 'image_url' which the UI will eventually use.
                found_art_path = self._find_local_art(abs_album_path, cache_dir)
                if not found_art_path and track_objects:
                    # Synthetic/meta albums (e.g. mixtapes) have no folder of their own. Build a
                    # 2x2 collage from the covers of their tracks' real source albums; fall back
                    # to a single borrowed cover (1 source), then the first track's folder art.
                    source_covers = collect_source_covers(root_dir, [t.uri for t in track_objects])
                    if len(source_covers) >= 2:
                        found_art_path = build_cover_collage(source_covers, cache_dir)
                    if not found_art_path:
                        if source_covers:
                            found_art_path = source_covers[0]
                        else:
                            first_track_dir = os.path.dirname(
                                os.path.normpath(os.path.join(root_dir, track_objects[0].uri))
                            )
                            found_art_path = self._find_local_art(first_track_dir, cache_dir)
                album_dict["display_image_url"] = found_art_path or KIVY_ICON
                # --------------------------------

                album_dict["tracks"] = track_objects
                album_obj = GenericAlbum(**album_dict)

                # Update the object with the found art path (or default if empty)
                album_obj.image_url = found_art_path or KIVY_ICON

                # 4. Populate Cache
                self.app.album_data_cache[album_obj.uri] = album_obj
                self.app.ordered_album_uris.append(album_obj.uri)

            Clock.schedule_once(self.app._populate_initial_lists)

        except Exception as e:
            err = str(e)
            Logger.error(f"LocalFilesClientHost: Threaded Parse Failed: {e}", exc_info=True)
            Clock.schedule_once(lambda dt: self.root_layout.set_status(f"Error: {err}"))

    def _find_local_art(self, album_path: str, cache_dir: str) -> str:
        """
        Helper to find album art.
        Priority:
        1. External files (cover.jpg, etc.)
        2. Embedded tags (MP3, FLAC, M4A, OGG)
        """
        if not os.path.isdir(album_path):
            return ""

        # A. Check for External Files (cover/folder/album/front .jpg/.jpeg/.png, AlbumArt*)
        external = find_cover_in_dir(album_path)
        if external:
            return external

        # B. Check for Embedded Art
        if not mutagen:
            return ""

        # Find any supported audio file
        valid_exts = (".mp3", ".flac", ".m4a", ".ogg", ".wma")
        first_audio = None
        for filename in os.listdir(album_path):
            if filename.lower().endswith(valid_exts):
                first_audio = os.path.join(album_path, filename)
                break

        if first_audio:
            # Use a hash of the file path for the cache key
            file_hash = hashlib.md5(first_audio.encode("utf-8")).hexdigest()
            # We guess .jpg initially, but the extractor might change it
            cached_art_path_base = os.path.join(cache_dir, file_hash)

            # Check if cached version exists (try common extensions)
            if os.path.exists(cached_art_path_base + ".jpg"):
                return cached_art_path_base + ".jpg"
            if os.path.exists(cached_art_path_base + ".png"):
                return cached_art_path_base + ".png"

            # Attempt extraction
            return self._extract_art_to_cache(first_audio, cached_art_path_base)

        return ""

    def _extract_art_to_cache(self, filepath, cache_path_base):
        """
        Inspects the file format and extracts binary image data.
        Returns the full path to the saved image, or "" if failed.
        """
        try:
            f = MutagenFile(filepath)
            if not f:
                return ""

            art_data = None
            ext = "jpg"  # Default assumption

            # 1. MP3 (ID3)
            if isinstance(f, MP3) or hasattr(f, "tags") and isinstance(f.tags, ID3):
                if f.tags:
                    # Look for APIC frames
                    for key in f.tags.keys():
                        if key.startswith("APIC"):
                            pic = f.tags[key]
                            art_data = pic.data
                            if "png" in pic.mime:
                                ext = "png"
                            break

            # 2. FLAC
            elif isinstance(f, FLAC):
                if f.pictures:
                    for p in f.pictures:
                        if p.type == 3:  # 3 = Front Cover
                            art_data = p.data
                            if p.mime == "image/png":
                                ext = "png"
                            break

            # 3. M4A (MP4)
            elif isinstance(f, MP4):
                # 'covr' is a list of data atoms
                if "covr" in f.tags:
                    art_data = f.tags["covr"][0]
                    # M4A doesn't give mime type easily, need to sniff bytes
                    # PNG starts with 89 50 4E 47
                    if art_data.startswith(b"\x89PNG"):
                        ext = "png"

            # 4. OGG (Vorbis)
            elif isinstance(f, OggVorbis):
                # Vorbis stores art as a base64 encoded string in 'metadata_block_picture'
                if "metadata_block_picture" in f.tags:
                    try:
                        b64_data = f.tags["metadata_block_picture"][0]
                        binary_data = base64.b64decode(b64_data)
                        # This binary block is actually a FLAC Picture structure
                        pic = Picture(binary_data)
                        art_data = pic.data
                        if pic.mime == "image/png":
                            ext = "png"
                    except Exception as e:
                        Logger.warning(f"LocalFiles: OGG art decode failed: {e}")

            # --- SAVE ---
            if art_data:
                final_path = f"{cache_path_base}.{ext}"
                with open(final_path, "wb") as img_f:
                    img_f.write(art_data)
                return final_path

        except Exception as e:
            Logger.warning(f"LocalFiles: Failed to extract art from {filepath}: {e}")

        return ""

    def start_polling(self):
        """Starts polling the audio player for position updates."""
        if not self.poll_event:
            self.poll_event = Clock.schedule_interval(self._update_progress_ui, 0.1)

    def stop_polling(self):
        if self.poll_event:
            self.poll_event.cancel()
            self.poll_event = None

    def _update_progress_ui(self, dt):
        if not self.is_playing:
            return
        player = self.app.audio_player
        if not player:
            return

        try:
            pos = player.get_position()
            dur = player.get_duration()

            widget = self.playback_info_widget
            if not widget:
                return

            # Elapsed time depends only on position, so update it every tick — even
            # before VLC has parsed the stream length (get_length() returns 0 for the
            # first moments of a track). Gating this behind `dur > 0` left the timer
            # frozen at "00:00" while audio was already playing (the intermittent
            # "0:00 - 0:00" display). Progress + total still wait for a known duration.
            widget.current_time = self.root_layout.format_duration(pos * 1000)
            if dur > 0:
                widget.progress_value = (pos / dur) * 100
                widget.total_time = self.root_layout.format_duration(dur * 1000)

        except Exception:
            pass

    def on_stop_click(self):
        self.stop_polling()
        self.is_playing = False
        self.current_playing_track_uri = None
        self.playback_queue = []
        self.queue_index = -1
        if self.playback_info_widget:
            self.playback_info_widget.track_title = "Stopped"
            self.playback_info_widget.progress_value = 0

    # --- Shuffle Trap (flagship trap effect) ---
    def _shuffle_trap_count(self):
        """Number of tracks one Shuffle Trap replays (client setting, default 1, min 1)."""
        try:
            return max(1, int(getattr(self.app, "shuffle_trap_count", 1)))
        except (TypeError, ValueError):
            return 1

    def _seek_trap_seconds(self):
        """Seek Trap jump magnitude in seconds (client setting, default 15, clamped 5-60)."""
        try:
            return max(5, min(60, int(getattr(self.app, "seek_trap_seconds", 15))))
        except (TypeError, ValueError):
            return 15

    def _resolve_trap_tracks(self, uris):
        """Map already-played track URIs to their real GenericTrack objects (correct
        title/artist) from the album cache, so the now-playing bar isn't blanked."""
        tracks = []
        for uri in uris:
            prog = self.app.track_progress.get(uri) or {}
            album = self.app.album_data_cache.get(prog.get("parent_uri"))
            if not album:
                continue
            for track in album.tracks:
                if track.uri == uri:
                    tracks.append(track)
                    break
        return tracks

    def on_trap_received(self, name: str) -> bool:
        """Route a received trap to its effect.

        Returns True when this host consumes the trap (the app then skips the reference
        modal). Each effect falls back to False on an empty/edge pool so the generic modal
        still gives feedback — never a silent no-op, never a softlock."""
        if name == "Seek Trap":
            return self._seek_trap()
        if name != "Shuffle Trap":
            return False

        pool = eligible_shuffle_tracks(self.app.track_progress, self.app.owned_albums)
        tracks = self._resolve_trap_tracks(
            pick_shuffle_tracks(pool, self._shuffle_trap_count(), random.Random())
        )
        if not tracks:
            return False  # nothing finished yet -> fall back to the reference modal

        if self._trap_playing:
            # Serialize: one Shuffle Trap at a time. Queue it; it starts (with a freshly
            # rolled pool) when the current forced replay ends. The original _trap_saved is
            # kept so the very last trap still resumes what was first interrupted.
            self._trap_pending += 1
        else:
            self._start_shuffle_trap(tracks)
        return True

    def _start_shuffle_trap(self, tracks):
        """Save current playback, then force-play the given already-finished tracks in order.
        Volume is left untouched (respects mute; no sudden-loud-volume per ROADMAP A1)."""
        self._trap_saved = {
            "queue": list(self.playback_queue),
            "index": self.queue_index,
            "uri": self.current_playing_track_uri,
            "was_playing": self.is_playing,
        }
        self._trap_playing = True
        self.app.show_toast(f"\U0001f3b5 Shuffle Trap! Replaying {len(tracks)} track(s)…")
        self.playback_queue = list(tracks)
        self.queue_index = 0
        self._play_track_internal(tracks[0])

    def _end_shuffle_trap(self):
        """A forced replay queue exhausted. Start a queued Shuffle Trap if one is pending;
        otherwise resume the interrupted playback (or park if nothing was playing)."""
        if self._trap_pending > 0:
            self._trap_pending -= 1
            pool = eligible_shuffle_tracks(self.app.track_progress, self.app.owned_albums)
            tracks = self._resolve_trap_tracks(
                pick_shuffle_tracks(pool, self._shuffle_trap_count(), random.Random())
            )
            if tracks:
                self.playback_queue = list(tracks)
                self.queue_index = 0
                self._play_track_internal(tracks[0])
                return

        # No (more) pending traps: restore prior state and clear trap flags.
        saved = self._trap_saved or {}
        self._trap_playing = False
        self._trap_saved = None
        self._trap_pending = 0

        resume_uri = saved.get("uri")
        resume_queue = saved.get("queue") or []
        resume_index = saved.get("index", -1)
        if saved.get("was_playing") and resume_uri and 0 <= resume_index < len(resume_queue):
            Logger.info("LocalFiles: Shuffle Trap done -> resuming interrupted playback.")
            self.playback_queue = list(resume_queue)
            self.queue_index = resume_index
            self._play_track_internal(resume_queue[resume_index])
        else:
            Logger.info("LocalFiles: Shuffle Trap done -> nothing to resume; parking.")
            self.is_playing = False
            self.current_playing_track_uri = None
            if self.playback_info_widget:
                self.playback_info_widget.track_title = "Finished"
                self.playback_info_widget.progress_value = 100
                self.playback_info_widget.current_time = "00:00"
            self.playback_queue = []
            self.queue_index = -1

    def _cancel_shuffle_trap(self):
        """User-initiated playback during a trap cancels the forced replay/restore cleanly."""
        self._trap_playing = False
        self._trap_saved = None
        self._trap_pending = 0

    # --- Seek Trap (yank the live playhead) ---
    def _seek_trap(self) -> bool:
        """Seek Trap: yank the current track's playhead back or forward by N seconds.

        Instantaneous (no save/restore queue needed — unlike the Shuffle Trap it doesn't take
        playback over for a duration). Direction is a random coin-flip each fire. The forward
        clamp (in seek_trap_target) keeps the tail playing so the track still finishes naturally
        and releases its AP check. Returns False with nothing playing so the reference modal
        still fires — never a silent no-op, never a softlock. Volume left untouched (ROADMAP A1)."""
        if not self.is_playing or not self.current_playing_track_uri:
            return False
        player = self.app.audio_player
        if not player:
            return False

        pos = player.get_position()
        dur = player.get_duration()
        sign = random.Random().choice((-1, 1))
        delta = sign * self._seek_trap_seconds()
        target = seek_trap_target(pos, dur, delta)
        player.set_position(target)

        arrow = "⏪" if sign < 0 else "⏩"  # rewind / fast-forward
        self.app.show_toast(f"{arrow} Seek Trap! Jumped {abs(delta)}s.")
        return True

    def on_playback_finished(self):
        Logger.info("LocalFiles: Track finished naturally.")

        # 1. Stop polling while we switch
        self.stop_polling()

        # 2. Handle completion logic. During a Shuffle Trap the queue is already-finished
        # tracks, so this block is naturally skipped (complete_track no-ops on finished
        # tracks); the _trap_playing guard keeps the guess-mode toast from firing either way.
        if self.current_playing_track_uri and not self._trap_playing:
            track_uri = self.current_playing_track_uri
            track_data = self.app.track_progress.get(track_uri)
            if track_data and not track_data["is_finished"]:
                if getattr(self.app, "guess_mode", False):
                    # Guess mode: finishing playback does NOT award the check — the player must
                    # name the track (per-row Guess button) to earn it.
                    self.app.show_toast("Track ended — guess it to score.")
                else:
                    self.root_layout.complete_track(track_uri)
                    self.app.show_toast(f"Finished: {self.current_playing_track_title}")

        # 3. Advance Queue
        next_index = self.queue_index + 1
        if 0 <= next_index < len(self.playback_queue):
            Logger.info(f"LocalFiles: Advancing queue to index {next_index}")
            self.queue_index = next_index
            next_track = self.playback_queue[next_index]
            self._play_track_internal(next_track)
        elif self._trap_playing:
            # Forced Shuffle Trap queue exhausted -> resume what was interrupted (or park).
            self._end_shuffle_trap()
        else:
            Logger.info("LocalFiles: Queue finished.")
            self.is_playing = False
            self.current_playing_track_uri = None
            if self.playback_info_widget:
                self.playback_info_widget.track_title = "Finished"
                self.playback_info_widget.progress_value = 100
                self.playback_info_widget.current_time = "00:00"
            self.playback_queue = []
            self.queue_index = -1

    def _play_track_internal(self, track_obj: GenericTrack):
        self.stop_polling()
        uri = track_obj.uri
        title = track_obj.title

        # Check ownership
        prog = self.app.track_progress.get(uri)
        parent = prog.get("parent_uri") if prog else None
        if (not parent or parent not in self.app.owned_albums) and not self.app.cheat_mode:
            self.app.show_toast(f"Skipping unowned: {title}")
            Clock.schedule_once(lambda dt: self.on_playback_finished(), 0.1)
            return

        abs_path = os.path.normpath(os.path.join(self.backend.root_directory, uri))
        if not os.path.exists(abs_path):
            self.app.show_toast(f"File not found: {title}")
            Clock.schedule_once(lambda dt: self.on_playback_finished(), 0.1)
            return

        # Update UI. In hidden mode, the currently-playing (not-yet-finished) track is the one
        # you're trying to recognize, so mask its title/artist in the now-playing bar too.
        if self.playback_info_widget:
            is_finished = bool(prog and prog.get("is_finished"))
            hidden = getattr(self.app, "hidden_metadata", False) and not is_finished
            parent_album = self.app.album_data_cache.get(parent)
            real_title = title
            real_artist_album = f"{track_obj.artist} - {track_obj.album_title}"
            real_art = (parent_album.image_url if parent_album else None) or KIVY_ICON
            # Always stash the real values so the D5 peek can reveal the now-playing bar even
            # while hidden mode shows placeholders.
            self.playback_info_widget.raw_title = real_title
            self.playback_info_widget.raw_artist_album = real_artist_album
            self.playback_info_widget.raw_art_source = real_art
            # In hidden mode the currently-playing (not-yet-finished) track is the one you're
            # trying to recognize, so mask its title/artist/cover in the now-playing bar too.
            if hidden:
                self.playback_info_widget.track_title = "Unknown Track"
                self.playback_info_widget.artist_album = "Unknown Artist"
                self.playback_info_widget.art_source = KIVY_ICON
            else:
                self.playback_info_widget.track_title = real_title
                self.playback_info_widget.artist_album = real_artist_album
                self.playback_info_widget.art_source = real_art

            self.playback_info_widget.progress_value = 0
            self.playback_info_widget.current_time = "00:00"

        # Play
        self.app.audio_player.play(abs_path)
        self.current_playing_track_uri = uri
        self.current_playing_track_title = title
        self.is_playing = True
        Clock.schedule_once(lambda dt: self.start_polling(), 0.5)

    def _play_track(self, track_uri: str, track_title: str):
        self.stop_polling()
        self._cancel_shuffle_trap()  # user took over -> drop any forced replay/restore
        # D7: auto-advance from the clicked track through the end of the album currently
        # shown (real or meta/Mixtape), instead of stopping after one track. Use the
        # displayed container, not track_progress' parent_uri, so a Mixtape continues
        # through itself rather than a source album.
        container_uri = getattr(self.app, "_current_track_container_uri", None)
        album = self.app.album_data_cache.get(container_uri) if container_uri else None
        queue = build_continuation_queue(album, track_uri) if album else []
        if not queue:
            # Unknown container / track not in it -> single-track fallback (never softlock).
            queue = [
                GenericTrack(
                    uri=track_uri,
                    title=track_title,
                    artist="",
                    album_title="",
                    duration_ms=0,
                    service="local",
                )
            ]
        self.playback_queue = queue
        self.queue_index = 0
        self._play_track_internal(queue[0])

    def _play_album(self, album_uri):
        """
        Loads all tracks from the album into the queue and starts playback.
        """
        self._cancel_shuffle_trap()  # user took over -> drop any forced replay/restore
        # 1. Check ownership
        if album_uri not in self.app.owned_albums and not self.app.cheat_mode:
            self.app.show_toast("You do not own this album yet.")
            return

        # 2. Get Album Data from Cache
        album = self.app.album_data_cache.get(album_uri)
        if not album or not album.tracks:
            self.app.show_toast("Error: Album has no tracks.")
            return

        # 3. Populate Queue
        self.playback_queue = list(album.tracks)  # Create a copy
        self.queue_index = 0

        Logger.info(f"LocalFiles: Queued {len(self.playback_queue)} tracks for album {album.title}")
        self.app.show_toast(f"Playing Album: {album.title}")

        # 4. Play First Track
        if self.playback_queue:
            self._play_track_internal(self.playback_queue[0])

    def on_play_pause_click(self):
        if self.is_playing:
            self.app.audio_player.pause()
            self.is_playing = False
            self.app.show_toast("Paused")
        else:
            if self.current_playing_track_uri:
                self.app.audio_player.resume()
                self.is_playing = True
                self.app.show_toast("Resumed")
            else:
                self.app.show_toast("Select a track to play.")

    def on_volume_change(self, new_volume: int):
        # Slider is 0-100, player wants 0.0-1.0
        vol_float = new_volume / 100.0
        self.app.audio_player.set_volume(vol_float)
        self.root_layout.set_status(f"Volume: {new_volume}%")

    def on_mute_toggle(self, is_muted: bool):
        # We don't need this, the RootLayout handles volume based on the slider state
        pass

    def on_device_select(self, device_name: str):
        pass  # Not supported

    def get_settings_ui(self) -> BoxLayout | None:
        """Local files require no extra settings."""
        return None

    def on_list_item_click(self, list_item):
        """Handles clicks on albums or tracks."""
        if list_item.raw_item_type == "album":
            if not list_item.is_owned and not self.app.cheat_mode:
                self.app.show_toast("You do not own this album yet.")
                return
            self.root_layout.set_status(f"Loading tracks for: {list_item.raw_title}")
            self.root_layout.populate_track_list(list_item.raw_uri)

        elif list_item.raw_item_type == "track":
            self._play_track(list_item.raw_uri, list_item.raw_title)

    def on_menu_action(self, option_text, list_item):
        """
        Handles both opening the menu and processing the result.
        """
        if option_text == "OPEN_MENU":
            # --- This is the menu-building logic ---
            menu = ItemMenu(caller=list_item, auto_width=False, width=dp(200))
            menu.clear_widgets()
            app = self.app
            cheat_color = "ff8888"
            button_added = False

            if list_item.raw_item_type == "album" or list_item.raw_item_type == "playlist":
                btn = Button(text="Play", size_hint_y=None, height=dp(44))
                btn.bind(on_release=lambda x: menu.on_option_select("Play Album"))
                menu.add_widget(btn)

                btn_hint = Button(text="Hint", size_hint_y=None, height=dp(44))
                btn_hint.bind(on_release=lambda x: menu.on_option_select("Hint"))
                menu.add_widget(btn_hint)
                button_added = True

            elif list_item.raw_item_type == "track":
                btn = Button(text="Play Track", size_hint_y=None, height=dp(44))
                btn.bind(on_release=lambda x: menu.on_option_select("Play Track"))
                menu.add_widget(btn)
                button_added = True

                # Hidden mode: let the player peek at an unrevealed track.
                if getattr(app, "hidden_metadata", False) and not list_item.is_finished:
                    btn_reveal = Button(text="Reveal", size_hint_y=None, height=dp(44))
                    btn_reveal.bind(on_release=lambda x: menu.on_option_select("Reveal"))
                    menu.add_widget(btn_reveal)

                if app.cheat_mode:
                    cheat_text = f"[color={cheat_color}]Send Location[/color]"
                    btn_send_loc = Button(
                        text=cheat_text, markup=True, size_hint_y=None, height=dp(44)
                    )
                    btn_send_loc.bind(on_release=lambda x: menu.on_option_select("Send Location"))
                    menu.add_widget(btn_send_loc)
                    button_added = True

            if not button_added:
                btn = Button(text="No actions", size_hint_y=None, height=dp(44))
                btn.bind(on_release=lambda x: menu.on_option_select("No actions"))
                menu.add_widget(btn)

            menu.open(list_item.ids.menu_button)  # Open relative to the button
            return

        # --- This is the action-handling logic ---
        elif option_text == "Play Album":
            self._play_album(list_item.raw_uri)

        elif option_text == "Play Track":
            self._play_track(list_item.raw_uri, list_item.raw_title)

        elif option_text == "Reveal":
            self.app.root.reveal_track(list_item.raw_uri)

        elif option_text == "Hint":
            apworld_name = list_item.text_line_4
            if self.app.ap_client and apworld_name:
                self.app.ap_client.send_chat_message(f"!hint {apworld_name}")
                self.app.show_toast(f"Hinting for: {apworld_name}")

        elif option_text == "Send Location":
            track_uri = list_item.raw_uri
            location_id = self.app.track_progress.get(track_uri, {}).get("location_id")
            if location_id and self.app.ap_client:
                self.app.ap_client.send_location_check(location_id)
                self.app.show_toast(f"CHEAT: Sent check for {list_item.raw_title}")
                if track_uri in self.app.track_progress:
                    self.app.track_progress[track_uri]["is_finished"] = True
                self.root_layout.update_track_ui(track_uri)


# -------------------------------------------------------------------
# 4. PLUGIN MANIFEST
# -------------------------------------------------------------------
MUSIPELAGO_PLUGIN = {
    "name": "Local Files",
    "generator_backend": LocalFilesBackendLogic,
    "generator_ui": LocalFilesHostUI,
    "client_backend": LocalFilesBackendLogic,
    "client_ui": LocalFilesClientHost,
}
