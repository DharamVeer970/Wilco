"""The tool set the agent can call.

Write a plain function in any module listed in MODULES and it becomes a tool. Its name,
signature and docstring become the schema the model sees, so there is no JSON to keep in
sync — the docstring IS the spec. Underscore-prefixed functions stay private.

Every tool returns a human-readable string. That is deliberate: the model reads the result
and can carry on talking about it, so an action and the conversation about it are the same
turn. Tools never speak — core/agent.py does that once, at the end.
"""
import inspect
import re
import time as _time
from typing import Union

from mcp_tool import gate, governance, message, pc, reminders, selftest, shell_tool, ui, voice, web, workflow, workspace
from mcp_tool.pc import apps as pc_apps, files as pc_files, input as pc_input, system as pc_system

# governance & extensibility (all off by default — see core/safety.py, core/plugins.py)
from core import plugins as _plugins
from core import safety as _safety

MODULES = (pc_apps, pc_input, pc_files, pc_system, ui, web, reminders, message, shell_tool, workflow, selftest, voice, gate, workspace, governance)
JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _json_type(param):
    """Prefer an annotation, else infer from the default — untyped params are strings.

    Handles the common container types too: list/tuple/set become arrays, dict becomes an
    object, and Optional[X] / X | None resolve to the wrapped type. Anything else falls back
    to string, which is the safe default for a spoken-command tool set.
    """
    annotation = param.annotation
    if annotation is inspect.Parameter.empty:
        # no annotation — infer from the default's type, else it's a string
        if param.default is not inspect.Parameter.empty and param.default is not None:
            annotation = type(param.default)
        else:
            return "string"

    # unwrap Optional[X] and X | None to the underlying type
    origin = getattr(annotation, "__origin__", None)
    if origin is Union:
        args = [a for a in getattr(annotation, "__args__", ()) if a is not type(None)]
        if len(args) == 1:
            annotation = args[0]
            origin = getattr(annotation, "__origin__", None)

    if origin is list or origin is tuple or origin is set:
        return "array"
    if origin is dict:
        return "object"
    if isinstance(annotation, type):
        return JSON_TYPES.get(annotation, "string")
    return "string"


def _schema(fn, description):
    properties, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        properties[name] = {"type": _json_type(param)}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "function", "function": {
        "name": fn.__name__,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


def _full_description(fn):
    """The whole docstring, normalised to one line — the spec for MCP clients and humans."""
    return " ".join((inspect.getdoc(fn) or "").split())


# The model gets a one-sentence summary instead of the full docstring.
_TOOL_DESC_MAX = 160


def _summary(fn):
    text = _full_description(fn)
    end = text.find(". ")
    first = text if end == -1 else text[: end + 1]
    if len(first) <= _TOOL_DESC_MAX:
        return first
    return first[:_TOOL_DESC_MAX - 1].rstrip() + "…"


def _public(module):
    return {name: fn for name, fn in vars(module).items()
            if not name.startswith("_") and inspect.isfunction(fn)
            and fn.__module__ == module.__name__}


REGISTRY = {name: fn for module in MODULES for name, fn in _public(module).items()}

# Extensibility: custom tools from plugins/ folder (only when WILCO_PLUGINS_ENABLED=1).
# Loaded lazily at import, merged into the same registry so they get schemas + dispatch.
for _pname, _pfn in _plugins.load_plugins().items():
    REGISTRY.setdefault(_pname, _pfn)

TOOLS = [_schema(fn, _full_description(fn)) for fn in REGISTRY.values()]
LLM_TOOLS = [_schema(fn, _summary(fn)) for fn in REGISTRY.values()]

# Tool aliases — Claude names mapped to Wilco tools without adding new schemas (90 stays 90).
TOOL_ALIASES = {
    "bash": "run_bash",
    "bashoutput": "run_bash",
    "glob": "find_files",
    "grep": "search_file_contents",
    "read": "read_file",
    "webfetch": "read_web_page",
    "websearch": "web_search",
    "todowrite": "self_check",
    "skill": "list_my_tools",
    "slashcommand": "list_my_tools",
}

# Models occasionally use the most natural argument spelling instead of the schema spelling
# (for example `path` for open_file).
_ARGUMENT_ALIASES = {
    "path": ("name", "folder_name"),
    "file_path": ("name", "path"),
    "filename": ("path", "name"),
    "file": ("name", "path"),
    "source": ("path", "name"),
    "directory": ("folder_name",),
    "folder": ("folder_name",),
    "content": ("text",),
    "pattern": ("text", "query", "name", "path"),
    "query": ("text", "name", "pattern"),
}


def _normalise_arguments(fn, arguments):
    """Return safe, schema-shaped arguments and whether an alias was repaired."""
    if not isinstance(arguments, dict):
        return arguments, False
    allowed = set(inspect.signature(fn).parameters)
    fixed, recovered = dict(arguments), False
    for supplied, targets in _ARGUMENT_ALIASES.items():
        if supplied not in fixed or supplied in allowed:
            continue
        target = next((name for name in targets if name in allowed and name not in fixed), None)
        if target:
            fixed[target] = fixed.pop(supplied)
            recovered = True
    return fixed, recovered

# ------------------------------------ tool dispatch ---------------------------
_STOPISH = frozenset("a an the and or but for with to of in on at by from you your he she "
                     "it we they be been is are was were do does did can could will would "
                     "should may might this that these those not no yes when where what "
                     "which who how all some any more most its it's i'm".split())
_WORD = re.compile(r"[a-z]{2,}")


def _token_set(text):
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPISH}


_TOOL_WORDS = {}
for t in LLM_TOOLS:
    name = t["function"]["name"]
    words = _token_set(name + " " + t["function"]["description"])
    for alias, target in TOOL_ALIASES.items():
        if target == name:
            words.add(alias)
    _TOOL_WORDS[name] = words

# Always on the wire — must never be missing, whatever the query looks like.
CORE_TOOLS = ("confirm_yes", "cancel_action", "run_powershell", "run_bash", "run_python",
              "web_search", "read_web_page", "list_my_tools", "self_check",
              "list_controls", "click_control", "set_screen_brightness",
              "get_screen_brightness", "set_volume", "change_volume", "get_volume",
              "mute_sound", "mute_state",
              "check_requirements", "install_requirements", "run_tests")


from collections import OrderedDict as _OrderedDict
_DISPATCH_CACHE: _OrderedDict[tuple[str, int], list] = _OrderedDict()
_DISPATCH_CACHE_MAX = 256


def dispatch_tools(query, limit):
    """The compact schemas for one turn: the `limit` most relevant tools plus CORE_TOOLS.

    `limit` <= 0 (or big enough to cover everything) sends every compact schema, i.e. no
    routing. The ranking is word-overlap between the query and each tool's own words, which
    keeps the model's pick to a small, focused list — a fraction of the old payload.

    Optimized: LRU cache on (query,limit) avoids re-ranking 90 tools twice per turn.
    """
    if limit <= 0 or len(LLM_TOOLS) <= limit + len(CORE_TOOLS):
        return LLM_TOOLS
    key = (query, limit)
    cached = _DISPATCH_CACHE.get(key)
    if cached is not None:
        _DISPATCH_CACHE.move_to_end(key)
        return cached
    tokens = _token_set(query)
    chosen = []
    if tokens:
        ranked = [(len(tokens & _TOOL_WORDS[name]), name) for name in _TOOL_WORDS]
        # Sort by score desc, then by name for stability; top `limit` most relevant
        ranked_sorted = sorted(ranked, key=lambda x: (x[0], x[1]), reverse=True)
        chosen = [name for _, name in ranked_sorted[:limit]]
    # CORE_TOOLS always appended but after ranked, preserves priority of ranked
    chosen.extend(name for name in CORE_TOOLS if name not in chosen)
    # Build result in ranked order (most relevant first) for model to see priority
    name_to_schema = {t["function"]["name"]: t for t in LLM_TOOLS}
    result = [name_to_schema[name] for name in chosen if name in name_to_schema]
    if len(_DISPATCH_CACHE) >= _DISPATCH_CACHE_MAX:
        _DISPATCH_CACHE.popitem(last=False)
    _DISPATCH_CACHE[key] = result
    return result


def call(name, arguments):
    """Run one tool and return its result as text.

    Never raises. A bad tool name, a wrong argument or a crash inside the tool all come back
    as a string, because the model can read that and try something else — whereas an
    exception here would kill the turn and leave the user with silence.
    """
    if isinstance(name, str):
        alias = TOOL_ALIASES.get(name.lower())
        if alias and alias in REGISTRY:
            name = alias
    fn = REGISTRY.get(name)
    if fn is None:
        hint = ""
        low = name.lower() if isinstance(name, str) else ""
        if low in TOOL_ALIASES:
            hint = f" (try {TOOL_ALIASES[low]} instead)"
        return f"No tool called {name}{hint}. Available: {', '.join(sorted(REGISTRY))}"
    arguments, recovered = _normalise_arguments(fn, arguments)
    if not isinstance(arguments, dict):
        return f"Wrong arguments for {name}: arguments must be an object."
    _start = _time.time()

    # Permission gate: block the tool outright if it's not allowed (off by default).
    if not _safety.check_permission(name):
        _safety.audit(tool=name, arguments=arguments, ok=False, note="denied by permission rule")
        return f"{name} is not permitted under the current rules. Ask to enable it, or rephrase."

    # Rate limiting: refuse when this tool has been used too often in its window.
    if not _safety._permitted_now(name):
        _safety.audit(tool=name, arguments=arguments, ok=False, note="rate limited")
        return f"{name} has been used too many times recently. Wait a moment and try again."

    try:
        result = str(fn(**arguments))
        if recovered:
            result = "Recovered the argument name automatically. " + result
        _safety.audit(tool=name, arguments=arguments, result_len=len(result),
                      ok=True, latency=_time.time() - _start, note="ok")
        return result
    except TypeError as e:
        _safety.audit(tool=name, arguments=arguments, ok=False,
                      latency=_time.time() - _start, note=f"bad args: {e}")
        return f"Wrong arguments for {name}: {e}"
    except Exception as e:
        _safety.audit(tool=name, arguments=arguments, ok=False,
                      latency=_time.time() - _start, note=f"{type(e).__name__}")
        return f"{name} failed: {type(e).__name__}: {e}"
