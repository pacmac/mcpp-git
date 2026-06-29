"""MCP tool entry point for mcpp-git.

Loaded by mcpp via spec_from_file_location. Provides execute() which
dispatches to GitCommands handlers.

Context (user/project/task/step) is passed explicitly in tool args.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


_pkg_dir = Path(__file__).resolve().parent
_file_logging_done = False


def _load_sibling(name: str):
    """Import a sibling .py file from this directory."""
    mod_name = f"mcpp_git.{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _pkg_dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_file_logging():
    global _file_logging_done
    if _file_logging_done:
        return
    _file_logging_done = True
    logger = logging.getLogger("mcpp_git")
    try:
        handler = RotatingFileHandler(
            str(_pkg_dir / "git.log"),
            maxBytes=512_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(asctime)s %(process)d %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    except Exception:
        pass


_tool_log = logging.getLogger("mcpp_git.tool")


def _get_commands():
    """Lazily build and return the GitCommands instance."""
    commands_mod = _load_sibling("commands")
    return commands_mod.GitCommands()


def execute(tool_name: str, arguments: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a git tool command via MCP interface."""
    workspace_dir = arguments.pop("workspace_dir", None) or (context or {}).get("workspace_dir", ".")
    _ensure_file_logging()
    _tool_log.debug("CALL %s args=%s", tool_name, arguments)

    cmds = _get_commands()
    table = cmds.dispatch_table()

    handler = table.get(tool_name)
    if not handler:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    try:
        result = handler(workspace_dir, arguments)
        _tool_log.debug("RESULT %s success=%s", tool_name, result.get("success"))
        return result
    except Exception as e:
        _tool_log.error("EXCEPTION %s: %s", tool_name, e, exc_info=True)
        return {"success": False, "error": str(e)}
