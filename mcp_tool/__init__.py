"""The tool set the agent can call.

Write a plain function in any module listed in MODULES and it becomes a tool. Its name,
signature and docstring become the schema the model sees, so there is no JSON to keep in
sync — the docstring IS the spec. Underscore-prefixed functions stay private.

Every tool returns a human-readable string. That is deliberate: the model reads the result
and can carry on talking about it, so an action and the conversation about it are the same
turn. Tools never speak — core/agent.py does that once, at the end.
"""
import inspect
from typing import Union

from mcp_tool import gate, message, pc, reminders, selftest, shell_tool, ui, voice, web, workflow

MODULES = (pc, ui, web, reminders, message, shell_tool, workflow, selftest, voice, gate)
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


def _schema(fn):
    properties, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        properties[name] = {"type": _json_type(param)}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "function", "function": {
        "name": fn.__name__,
        "description": " ".join((inspect.getdoc(fn) or "").split()),
        "parameters": {"type": "object", "properties": properties, "required": required}}}


def _public(module):
    return {name: fn for name, fn in vars(module).items()
            if not name.startswith("_") and inspect.isfunction(fn)
            and fn.__module__ == module.__name__}


REGISTRY = {name: fn for module in MODULES for name, fn in _public(module).items()}
TOOLS = [_schema(fn) for fn in REGISTRY.values()]


def call(name, arguments):
    """Run one tool and return its result as text.

    Never raises. A bad tool name, a wrong argument or a crash inside the tool all come back
    as a string, because the model can read that and try something else — whereas an
    exception here would kill the turn and leave the user with silence.
    """
    fn = REGISTRY.get(name)
    if fn is None:
        return f"No tool called {name}. Available: {', '.join(REGISTRY)}"
    try:
        return str(fn(**arguments))
    except TypeError as e:
        return f"Wrong arguments for {name}: {e}"
    except Exception as e:
        return f"{name} failed: {type(e).__name__}: {e}"
