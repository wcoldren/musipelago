"""Tests for PluginManager discovery (the generator/client backend loader).

Uses an isolated temp directory with hand-written plugin files rather than the real
``plugins/`` dir, so the test is hermetic and doesn't drag in backend module imports.
"""
from musipelago.plugin_loader import PluginManager

GOOD_PLUGIN = '''
MUSIPELAGO_PLUGIN = {
    "name": "Demo Backend",
    "generator_backend": object,
    "generator_ui": object,
    "client_backend": object,
    "client_ui": object,
}
'''

NOT_A_DICT = '''
MUSIPELAGO_PLUGIN = "oops, not a dict"
'''

NO_MANIFEST = '''
SOMETHING_ELSE = 123
'''

UI_ONLY = '''
MUSIPELAGO_PLUGIN = {"name": "Client Only", "client_backend": object, "client_ui": object}
'''


def _write(d, name, body):
    (d / name).write_text(body, encoding="utf-8")


def test_discovers_only_valid_manifests(tmp_path):
    _write(tmp_path, "demo.py", GOOD_PLUGIN)
    _write(tmp_path, "broken.py", NOT_A_DICT)
    _write(tmp_path, "plain.py", NO_MANIFEST)
    _write(tmp_path, "__init__.py", "")          # must be skipped

    pm = PluginManager(plugin_dir=str(tmp_path))
    pm.discover_plugins()

    assert set(pm.plugins) == {"demo"}
    assert pm.get_plugin_manifest("demo")["name"] == "Demo Backend"


def test_get_available_backends_filters_by_app_type(tmp_path):
    _write(tmp_path, "demo.py", GOOD_PLUGIN)     # has generator_backend + generator_ui
    _write(tmp_path, "clientonly.py", UI_ONLY)   # no generator_* pair

    pm = PluginManager(plugin_dir=str(tmp_path))
    pm.discover_plugins()

    assert pm.get_available_backends("generator_backend") == ["demo"]
    assert set(pm.get_available_backends("client_backend")) == {"demo", "clientonly"}


def test_missing_dir_is_created(tmp_path):
    target = tmp_path / "made_on_demand"
    assert not target.exists()
    PluginManager(plugin_dir=str(target))
    assert target.exists()
