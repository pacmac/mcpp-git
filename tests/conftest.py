"""Test configuration — make mcpp_git importable via dynamic loading."""

import importlib.util
import sys
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent.parent


def _load_as(name: str):
    """Load a .py file from the package dir and register it as mcpp_git.{name}."""
    mod_name = f"mcpp_git.{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _pkg_dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Pre-load all modules so `from mcpp_git.git import ...` works in tests
_load_as("git")
_load_as("config")
_load_as("commands")
