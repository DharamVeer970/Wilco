"""Extensibility for Wilco: plugin tool modules + saveable configuration profiles.

Two independent features:

  - Plugins  : any .py file in the plugins/ folder whose functions match the same
    convention as mcp_tool modules (public, non-underscore, having a docstring) becomes
    part of the tool registry at load. This lets users add custom tools without editing
    core code.

  - Profiles : save and load named bundles of key config values (like a .env snapshot)
    so Wilco can be switched between 'home', 'work', 'demo', etc.

Both are off by default; see the .env flags below.
"""
import importlib.util
import json
import os
from pathlib import Path

from config import _flag

PLUGINS_ENABLED = _flag("WILCO_PLUGINS_ENABLED", False)
PROFILES_ENABLED = _flag("WILCO_PROFILES_ENABLED", False)

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "plugins"
PROFILES_FILE = Path.home() / ".wilco" / "profiles.json"

# --- plugins -------------------------------------------------------------------------
# A plugin file is a plain module whose public functions become tools, exactly like the
# MODULES in mcp_tool. It should import what it needs at the top and never run side
# effects at import time.
def discover_plugins():
    """Return a list of plugin module paths (in plugins/) that are safe to load."""
    if not PLUGINS_ENABLED or not PLUGIN_DIR.is_dir():
        return []
    files = sorted(PLUGIN_DIR.glob("plugin_*.py"))
    return [f for f in files if f.name != "__init__.py"]


def load_plugins():
    """Import every plugin module and collect its public callables.

    Returns {tool_name: callable}. Safe — a bad plugin is skipped, not fatal.
    """
    loaded = {}
    if not PLUGINS_ENABLED:
        return loaded
    for path in discover_plugins():
        try:
            name = f"wilco_plugin_{path.stem}"
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for attr in vars(module).values():
                if callable(attr) and getattr(attr, "__module__", "") == module.__name__ \
                        and not attr.__name__.startswith("_") \
                        and (attr.__doc__ or "").strip():
                    loaded[attr.__name__] = attr
        except Exception as e:  # a broken plugin must not take Wilco down
            print(f"  [plugin {path.name} skipped: {type(e).__name__}: {e}]")
    return loaded


# --- configuration profiles ------------------------------------------------------------
# A profile is a mapping of config-variable name -> value. Saving writes one; loading
# applies it into os.environ (and therefore config, which reads .env + environ live).
_KNOWN_KEYS = (
    "WILCO_TOOL_LIMIT", "WILCO_MAX_STEPS", "WILCO_VOICE", "WILCO_SPEED",
    "WILCO_PERMISSIONS_ENABLED", "WILCO_AUDIT_ENABLED", "WILCO_RATE_LIMIT_ENABLED",
    "WILCO_TOOL_ALLOW", "WILCO_TOOL_DENY", "WILCO_FEEDBACK_ENABLED",
    "WILCO_PLANNING_THRESHOLD",
)


def _load_profiles():
    if not PROFILES_FILE.exists():
        return {}
    try:
        data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_profiles(data):
    try:
        PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROFILES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def save_profile(name: str, keys=()):
    """Snapshot the given config values (or all known ones) under a profile name."""
    if not PROFILES_ENABLED:
        return False
    keys = tuple(keys) or _KNOWN_KEYS
    profiles = _load_profiles()
    profiles[name] = {k: os.environ.get(k) for k in keys if os.environ.get(k) is not None}
    _save_profiles(profiles)
    return True


def apply_profile(name: str):
    """Apply a saved profile's values into os.environ (effective immediately)."""
    if not PROFILES_ENABLED:
        return False
    profiles = _load_profiles()
    if name not in profiles:
        return False
    for k, v in profiles[name].items():
        if isinstance(v, str):
            os.environ[k] = v
    return True


def list_profiles():
    """The names of all saved profiles."""
    return sorted(_load_profiles().keys())
