# -*- coding: utf-8 -*-
import os, sys, json
# dotenv is no longer needed here
from unidecode import unidecode

KIVY_ICON = 'data/logo/kivy-icon-64.png'

# --- Helpers ---

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev, pipx, and PyInstaller """
    
    # 1. PyInstaller --onefile
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    
    # 2. PyInstaller --onedir
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
        # Check for PyInstaller 6+ _internal folder
        internal_path = os.path.join(base_path, '_internal')
        if os.path.exists(internal_path):
            return os.path.join(internal_path, relative_path)
        return os.path.join(base_path, relative_path)

    # 3. Development / Pip / Pipx
    # Anchors to the location of THIS file (utils.py)
    base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# --- Jinja2 Filters ---

def filter_to_ascii(text):
    return unidecode(str(text))

def filter_py_json(value):
    return json.dumps(value)

# --- Local-files cover-art discovery (pure; used by the local_files backend) ---
# Common cover filenames, by stem. We accept .jpg/.jpeg/.png for each, plus any
# file whose name starts with "albumart" (Windows Media Player's AlbumArt*.jpg).
_COVER_STEMS = ('cover', 'folder', 'album', 'front')
_COVER_EXTS = ('.jpg', '.jpeg', '.png')

def is_cover_filename(name):
    """True if a filename looks like a standalone album-cover image."""
    low = (name or "").lower()
    if low.startswith('albumart') and low.endswith(_COVER_EXTS):
        return True
    stem, ext = os.path.splitext(low)
    return stem in _COVER_STEMS and ext in _COVER_EXTS

def find_cover_in_dir(dirpath):
    """Return the path to a cover image in dirpath, or '' if none.

    Scans in sorted order so the choice is deterministic (and prefers 'album'/'cover'
    over 'folder'/'front' alphabetically). Pure — only touches the filesystem, no Kivy."""
    if not dirpath or not os.path.isdir(dirpath):
        return ""
    for filename in sorted(os.listdir(dirpath)):
        if is_cover_filename(filename):
            return os.path.join(dirpath, filename)
    return ""