"""Tests for local-files cover-art discovery (B3 follow-up).

`is_cover_filename` / `find_cover_in_dir` live in ``utils`` (pure — only the filesystem,
no Kivy/VLC) and back the local_files backend's `_find_local_art`. They broaden the old
exact-name check (cover.jpg/cover.png/folder.jpg/album.jpg) to the common variants, and the
directory scan is reused for the meta-album (mixtape) cover fallback.
"""
import os
from musipelago.utils import is_cover_filename, find_cover_in_dir


def test_recognizes_common_cover_names():
    for name in ['cover.jpg', 'Cover.JPG', 'cover.jpeg', 'cover.png',
                 'folder.jpg', 'folder.png', 'album.jpeg', 'front.png',
                 'AlbumArt_Large.jpg', 'albumart.png']:
        assert is_cover_filename(name), name


def test_rejects_non_cover_files():
    for name in ['track01.mp3', 'band.jpg', 'scan.tiff', 'notes.txt',
                 'cover.gif', 'coverart.bmp', '', None]:
        assert not is_cover_filename(name), name


def test_find_cover_returns_path(tmp_path):
    (tmp_path / 'cover.jpg').write_bytes(b'x')
    (tmp_path / '01 - song.flac').write_bytes(b'x')
    assert find_cover_in_dir(str(tmp_path)) == str(tmp_path / 'cover.jpg')


def test_find_cover_handles_variant_name(tmp_path):
    # the old code would have missed folder.png entirely
    (tmp_path / 'folder.png').write_bytes(b'x')
    assert find_cover_in_dir(str(tmp_path)) == str(tmp_path / 'folder.png')


def test_find_cover_none_when_no_image(tmp_path):
    (tmp_path / '01 - song.mp3').write_bytes(b'x')
    (tmp_path / 'readme.txt').write_bytes(b'x')
    assert find_cover_in_dir(str(tmp_path)) == ''


def test_find_cover_missing_dir():
    assert find_cover_in_dir('/no/such/dir') == ''
    assert find_cover_in_dir('') == ''


def test_find_cover_is_deterministic(tmp_path):
    # multiple covers -> alphabetical first (album < cover < folder), so the choice is stable
    for n in ['folder.jpg', 'cover.jpg', 'album.jpg']:
        (tmp_path / n).write_bytes(b'x')
    assert find_cover_in_dir(str(tmp_path)) == str(tmp_path / 'album.jpg')
