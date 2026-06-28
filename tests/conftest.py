"""Shared pytest setup for the Musipelago suite.

Two headless Kivy traps (see the project's headless-testing notes) are handled here
so individual test modules don't repeat the incantation:

1. Kivy can't open a real window under CI / a dummy display — force the dummy SDL
   driver and silence Kivy's arg parsing + console log BEFORE anything imports kivy.
2. Importing kivy replaces ``sys.excepthook`` and routes tracebacks to its logfile.
   pytest's assertion rewriting doesn't depend on it, but we restore the default
   hook defensively so any genuinely-uncaught error still surfaces normally.

Because pytest imports this conftest before collecting (and thus importing) the test
modules, setting the env vars at import time here runs before kivy is ever imported.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")

import sys

import pytest


@pytest.fixture(autouse=True)
def _restore_excepthook():
    """Undo Kivy's ``sys.excepthook`` override around every test."""
    sys.excepthook = sys.__excepthook__
    yield
    sys.excepthook = sys.__excepthook__
