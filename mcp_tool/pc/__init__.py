"""Facade for mcp_tool/pc/* — keeps `import mcp_tool.pc` working.

All tools live in mcp_tool/pc/apps, input, files, system. This __init__
re-exports them so old imports (`mcp_tool.pc.open_app`) still resolve, while
`mcp_tool/__init__.py:MODULES` registers the submodules directly.
"""
from mcp_tool.pc.common import KINDS, TEXT_EXTS, SKIP_DIRS, _resolve, _resolve_read, _resolve_write, _existing_file  # noqa: F401
from mcp_tool.pc.apps import (  # noqa: F401
    open_app, open_browser_window, close_app, close_tab, close_window,
    list_installed_apps, list_open_windows, focus_window,
)
from mcp_tool.pc.input import type_text, press_key, scroll, search_in_windows, clipboard  # noqa: F401
from mcp_tool.pc.files import (  # noqa: F401
    open_folder, find_files, search_file_contents, open_directory, list_drives,
    file_info, open_file, list_folder_contents, read_file, write_file, edit_file,
    manage_file, delete_file,
)
from mcp_tool.pc.system import (  # noqa: F401
    set_volume, change_volume, mute_sound, mute_state, get_volume,
    get_screen_brightness, set_screen_brightness, media_control,
    open_windows_settings, wifi_switch, wifi_password, system_info,
    check_windows_updates, power_action, take_screenshot, current_time,
    lock_screen, cancel_shutdown, empty_recycle_bin,
)
