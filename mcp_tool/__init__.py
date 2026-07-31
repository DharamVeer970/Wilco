"""The tool set the agent can call.

Write a plain function in any module listed in MODULES and it becomes a tool. Its name,
signature and docstring become the schema the model sees, so there is no JSON to keep in
sync — the docstring IS the spec. Underscore-prefixed functions stay private.

Every tool returns a human-readable string. That is deliberate: the model reads the result
and can carry on talking about it, so an action and the conversation about it are the same
turn. Tools never speak — core/agent.py does that once, at the end.
"""
import inspect

from mcp_tool import gate, pc, shell_tool, ui, web

MODULES = (pc, ui, web, shell_tool, gate)
JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _json_type(param):
    """Prefer an annotation, else infer from the default — untyped params are strings."""
    if param.annotation is not inspect.Parameter.empty:
        return JSON_TYPES.get(param.annotation, "string")
    if param.default is not inspect.Parameter.empty and param.default is not None:
        return JSON_TYPES.get(type(param.default), "string")
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
