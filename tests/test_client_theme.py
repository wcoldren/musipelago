"""Tests for B2 client theming: ``MusipelagoClientApp.apply_theme`` swaps the live palette.

Per the headless-testing notes, importing the client module is fine but instantiating Kivy
widgets is not — so we bind the real ``apply_theme`` onto a plain stub via ``types.MethodType``
(mirrors ``test_gen_ui.py``) and record persistence instead of touching a JsonStore.
"""

import types

import musipelago.musipelago_client as mc
import musipelago.theme as theme


def _make_app(monkeypatch):
    """Stub app with the real ``apply_theme`` bound and a recording ``_save_client_settings``.

    ``apply_theme`` sets ``Window.clearcolor``; the headless dummy Window can't take it, so
    swap in a plain stand-in (the real GUI always has a usable Window)."""
    monkeypatch.setattr(mc, "Window", types.SimpleNamespace(clearcolor=None))
    app = types.SimpleNamespace(theme_name="dark", saved=0)
    for key in theme.KEYS:
        setattr(app, f"col_{key}", theme.DARK[key])
    app.apply_theme = types.MethodType(mc.MusipelagoClientApp.apply_theme, app)
    app._save_client_settings = lambda: setattr(app, "saved", app.saved + 1)
    return app


def test_apply_theme_light_swaps_all_colors_and_persists(monkeypatch):
    app = _make_app(monkeypatch)
    app.apply_theme("light")
    assert app.theme_name == "light"
    for key in theme.KEYS:
        assert getattr(app, f"col_{key}") == theme.LIGHT[key]
    assert app.saved == 1  # persisted by default


def test_apply_theme_no_persist(monkeypatch):
    app = _make_app(monkeypatch)
    app.apply_theme("light", persist=False)
    assert app.theme_name == "light"
    assert app.saved == 0


def test_apply_theme_invalid_name_falls_back_to_dark(monkeypatch):
    app = _make_app(monkeypatch)
    app.theme_name = "light"
    app.apply_theme("nonsense")
    assert app.theme_name == "dark"
    for key in theme.KEYS:
        assert getattr(app, f"col_{key}") == theme.DARK[key]


def test_apply_theme_is_case_insensitive(monkeypatch):
    app = _make_app(monkeypatch)
    app.apply_theme("LIGHT", persist=False)
    assert app.theme_name == "light"
    assert app.col_bg == theme.LIGHT["bg"]
