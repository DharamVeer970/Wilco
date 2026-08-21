"""Instant-path step handlers — split from core/commands.py.

Each _step_* returns "command" if it handled the query, else None.
Lazy imports from core.commands avoid a circular import at load time.
"""
import os
import re
import webbrowser

import windows.files as files
import windows.shell as shell
from core.commands.patterns import (
    APP_SUFFIX, CANCEL, CODE_WRITE, COMPOSE, DIGIT, DIR_NAMED, DIR_PATH, DOWN, DRIVES,
    FILE_INFO, FILE_SEARCH, IN_WINDOWS, LIST_DRIVES, MEDIA, MEDIA_WORDS, MUTE,
    NAMED_FOLDER, ON_SITE, ONLINE, OPEN, PING, PLAY, RECYCLE, SEARCH, SEARCH_FOR,
    SETTINGS, SHOW, STRIP, TALK, TYPE, TYPE_SPOKEN, VOLUME, WIFI, BRIGHT, SITES,
)
from windows.speech import speak


def _step_site(query, _spoken):
    site = next((s for s in SITES if f"open {s}" in query), None)
    if not site:
        return None
    speak(f"Opening {site}.")
    webbrowser.open(SITES[site])
    return "command"


def _step_time(query, _spoken):
    if "the time" not in query:
        return None
    from core.commands import do
    do("time", "")
    return "command"


def _step_ai(query, _spoken):
    if "using artificial intelligence" not in query:
        return None
    from core.brain import ai
    ai(query)
    return "command"


def _step_reset_chat(query, _spoken):
    if "reset chat" not in query:
        return None
    from core import agent
    agent.reset()
    speak("Chat history reset.")
    return "command"


def _step_type(query, spoken):
    m = TYPE.match(query)
    if not m or COMPOSE.search(m.group(1).strip(STRIP)):
        return None
    if CODE_WRITE.search(m.group(1)) or CODE_WRITE.search(query):
        return None
    exact = TYPE_SPOKEN.search(spoken)
    from core.commands import do
    do("type_text", (exact or m).group(1).strip(STRIP))
    return "command"


def _step_show(query, _spoken):
    m = SHOW.match(query)
    from core.commands import _kind, show_in_folder
    kind = _kind(m.group(1)) if m else None
    if not kind:
        return None
    show_in_folder(kind, m.group(2))
    return "command"


def _step_windows_search(query, _spoken):
    m = IN_WINDOWS.match(query)
    if not m:
        return None
    from core.commands import do
    do("windows_search", m.group(1).strip(STRIP))
    return "command"


def _step_folder(query, _spoken):
    m = NAMED_FOLDER.match(query)
    if not m:
        return None
    from core.commands import do
    do("open_folder", m.group(1))
    return "command"


def _step_file_search(query, _spoken):
    m = FILE_SEARCH.match(query)
    text = m.group(1).strip(STRIP) if m else ""
    if not text:
        return None
    from mcp_tool.pc.files import search_file_contents
    result = search_file_contents(text)
    speak(result[:400] if len(result) > 400 else result)
    return "command"


def _step_directory(query, _spoken):
    m = DIR_NAMED.match(query) or DIR_PATH.match(query)
    if not m:
        return None
    from mcp_tool.pc.files import open_directory
    speak(open_directory(m.group(1)))
    return "command"


def _step_drives(query, _spoken):
    if not (DRIVES.fullmatch(query) or LIST_DRIVES.fullmatch(query)):
        return None
    from mcp_tool.pc.files import list_drives
    speak(list_drives())
    return "command"


def _step_file_info(query, _spoken):
    m = FILE_INFO.match(query)
    if not m:
        return None
    from mcp_tool.pc.files import file_info
    speak(file_info(m.group(1).strip(STRIP)))
    return "command"


def _step_mute(query, _spoken):
    if not MUTE.fullmatch(query):
        return None
    from core.commands import do
    do("mute", "")
    return "command"


def _step_volume(query, _spoken):
    if not VOLUME.search(query):
        return None
    from core.commands import do
    if DIGIT.search(query):
        do("set_volume", query)
    else:
        do("volume_down" if DOWN.search(query) else "volume_up", "")
    return "command"


def _step_talk_speed(query, _spoken):
    if not TALK.search(query):
        return None
    from core.commands import do
    do("speech_speed", query)
    return "command"


def _step_brightness(query, _spoken):
    if not BRIGHT.search(query):
        return None
    from core.commands import do
    do("set_brightness", query)
    return "command"


def _step_wifi(query, _spoken):
    m = WIFI.fullmatch(query)
    state = (m.group(1) or m.group(2)) if m else None
    if not state:
        return None
    from core.commands import do
    do("wifi_on" if state == "on" else "wifi_off", "")
    return "command"


def _step_media(query, _spoken):
    word = MEDIA.fullmatch(query)
    from core.commands import do
    if not (word and do("media", MEDIA_WORDS[word.group(1)])):
        return None
    return "command"


def _step_cancel_shutdown(query, _spoken):
    if not CANCEL.fullmatch(query):
        return None
    from core.commands import do
    do("cancel_shutdown", "")
    return "command"


def _step_power(query, _spoken):
    from core.commands.patterns import POWER, THIS_PC
    action = next((a for p, a in POWER if re.fullmatch(f"(?:{p}){THIS_PC}", query)), None)
    if not action:
        return None
    from core.commands import do
    do(action, "")
    return "command"


def _step_recycle_bin(query, _spoken):
    if not RECYCLE.search(query):
        return None
    from core.commands import do
    do("empty_recycle_bin", "")
    return "command"


def _step_ping(query, _spoken):
    m = PING.fullmatch(query)
    if not m:
        return None
    speak(shell.ping(m.group(1)) or f"Couldn't reach {m.group(1)}.")
    return "command"


def _step_system_info(query, _spoken):
    from core.commands import system_info
    said = system_info(query)
    if not said:
        return None
    speak(said)
    return "command"


def _step_kind(query, _spoken):
    from core.commands import _kind_asked_for, _browse
    kind = _kind_asked_for(query)
    if not kind:
        return None
    _browse(kind)
    return "command"


def _step_play(query, _spoken):
    m = PLAY.match(query)
    if not m:
        return None
    from core.commands import play_online
    play_online(m.group(1).strip(STRIP))
    return "command"


def _step_search(query, _spoken):
    m = SEARCH_FOR.match(query)
    if not m:
        return None
    text = m.group(1).strip(STRIP)
    on = ON_SITE.search(text)
    site = on.group(1) if on and on.group(1) in SEARCH else None
    if not text or not (site or query.startswith("google")):
        return None
    if site:
        text = text[: on.start()].strip(STRIP)
    if not text:
        return None
    from core.commands import play_online, web_search
    play_online(text) if site == ONLINE else web_search(text, site or "google")
    return "command"


def _step_settings(query, _spoken):
    from core.commands import do
    return "command" if SETTINGS.search(query) and do("open_settings", query) else None


def _step_open(query, _spoken):
    m = OPEN.match(query)
    if not m:
        return None
    name = APP_SUFFIX.sub("", m.group(1).strip(STRIP)).rstrip()
    name = re.sub(r"\s+for\s+me(?:\s+to\s+(?>view|see))?$", "", name)
    from core import context
    if (re.fullmatch(r"(?:it|that|this|(?:this|that|the) (?:file|image|screenshot|photo|picture))", name)
            and context.file and os.path.isfile(context.file)):
        kind = files.EXT_KIND.get(os.path.splitext(context.file)[1].lower(), "document")
        from core.commands import _open_path
        _open_path(kind, os.path.splitext(os.path.basename(context.file))[0], context.file)
        return "command"
    from core.commands import open_app, open_any_file
    return "command" if open_app(name) or open_any_file(name) else None


STEPS = (_step_site, _step_time, _step_ai, _step_reset_chat, _step_type, _step_show,
         _step_windows_search, _step_folder, _step_file_search, _step_directory,
         _step_drives, _step_file_info, _step_mute, _step_volume, _step_talk_speed,
         _step_brightness, _step_wifi, _step_media, _step_cancel_shutdown, _step_power,
         _step_recycle_bin, _step_ping, _step_system_info, _step_kind, _step_play,
         _step_search, _step_settings, _step_open)
