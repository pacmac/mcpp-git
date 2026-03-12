"""Configuration for mcpp-git.

Git-specific settings. Can be used standalone or integrated with
mcpp-plan's config system.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml


DEFAULTS: dict[str, Any] = {
    "enable_worktrees": False,
}


def _find_config_path(workspace_dir: Optional[str] = None) -> Optional[Path]:
    """Find config.yaml — check workspace_dir first, then module dir."""
    if workspace_dir:
        p = Path(workspace_dir) / "config.yaml"
        if p.exists():
            return p
    p = Path(__file__).resolve().parent / "config.yaml"
    if p.exists():
        return p
    return None


def get_config(workspace_dir: Optional[str] = None) -> dict[str, Any]:
    """Load git-specific config. Returns defaults if no config file found."""
    path = _find_config_path(workspace_dir)
    if path:
        try:
            with open(path) as f:
                user_cfg = yaml.safe_load(f)
            if isinstance(user_cfg, dict):
                # Extract from workflow section (mcpp-plan compat) or top-level
                workflow = user_cfg.get("workflow", {})
                if isinstance(workflow, dict):
                    result = dict(DEFAULTS)
                    for key in DEFAULTS:
                        if key in workflow:
                            result[key] = workflow[key]
                        elif key in user_cfg:
                            result[key] = user_cfg[key]
                    return result
        except (yaml.YAMLError, OSError):
            pass
    return dict(DEFAULTS)
