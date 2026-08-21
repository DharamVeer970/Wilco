"""Example plugin tool for Wilco.

Any plugin_*.py file in the plugins/ folder is loaded as a source of tools when
WILCO_PLUGINS_ENABLED=1. Public functions with a docstring become tools, exactly like
mcp_tool modules — their signature and docstring become the schema the model sees.

Try it:
    set WILCO_PLUGINS_ENABLED=1
    python -c "import mcp_tool; print('fortune' in mcp_tool.REGISTRY); print(mcp_tool.call('fortune_today', {}))"
"""
import secrets


def fortune_today():
    """Give a random short work-life tip for today. There's no wrong time to hear one."""
    tips = [
        "Take a two-minute breathing break — it resets your focus.",
        "The hardest part is starting; open the file and go.",
        "Big wins usually hide behind a dozen small, boring steps.",
        "Close the tabs you are not using; your head will thank you.",
        "You have solved harder problems than the one in front of you.",
    ]
    return secrets.choice(tips)  # S2245 safe: non-crypto random for tips