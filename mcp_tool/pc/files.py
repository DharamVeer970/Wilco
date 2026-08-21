"""File and folder tools — split from mcp_tool/pc.py."""
import os
import shutil

import windows.files as files
import windows.shell as shell
import windows.system as system
from config import TEXT_LIMIT
from core import context
from mcp_tool.gate import _park
from mcp_tool.pc.common import (
    KINDS, _kinds_for, _existing_file, _resolve, _resolve_read,
    _resolve_write, _text_files, _holds, _write, _new_folder,
    _destination_for, _carry_out,
)


def open_folder(name):
    """Open a folder in File Explorer. Known names — downloads, documents, desktop, pictures,
    music, videos — resolve instantly; anything else is searched for across the drives."""
    path = system.open_folder(name)
    if path:
        context.folder = path
        return f"Opened your {name} folder ({path})."
    found = files.folder_matches(name)
    if not found:
        return f"No folder called {name} anywhere on the drives."
    if len(found) > 1:
        listed = "; ".join(f"{n} in {p}" for n, p in found)
        return (f"{len(found)} folders match: {listed}. Ask the user which, then call "
                f"open_folder with a more specific name.")
    folder_name, path = found[0]
    files.open_file(path)
    context.folder = path
    return f"Opened {folder_name} at {path}."


def find_files(name, kind="any"):
    """Find files by name across the drives. kind: music, video, image, document, or any.
    Returns what matched — use open_file to actually open one. The first call of the session
    scans the disks and takes a few seconds."""
    direct = _existing_file(name)
    if direct:
        file_kind = files.EXT_KIND.get(os.path.splitext(direct)[1].lower(), "file")
        return f"1 match: {os.path.basename(direct)} ({file_kind}) in {os.path.dirname(direct)}"
    kinds, error = _kinds_for(kind)
    if error:
        return error
    hits = [(k, n, p) for k in kinds for n, p in files.matches(k, name)]
    if not hits:
        return f"No {kind} files matching {name}."
    return f"{len(hits)} matches: " + "; ".join(f"{n} ({k}) in {os.path.dirname(p)}"
                                                for k, n, p in hits[:15])


def search_file_contents(text, folder="", max_results=10):
    """Search the CONTENTS of files on this computer for a word or phrase — offline, no
    internet. This is how you answer "find the file that mentions X", "which file has my
    password", "search my notes for Y". Searches text files (txt, md, py, json, csv, log,
    config, code) under a folder, or the whole user profile if none is given. Returns the
    file paths that contain the text. Use find_files for searching by NAME instead."""
    text_lower = text.strip().lower()
    if not text_lower:
        return "What text should I search for?"
    where = folder.strip() or os.path.expanduser("~")
    if not os.path.isdir(where):
        return f"There's no folder at {where}."
    hits = []
    try:
        for path in _text_files(where):
            if _holds(path, text_lower):
                hits.append(path)
                if len(hits) >= int(max_results):
                    break
    except OSError as e:
        return f"Couldn't search {where}: {e.strerror or e}"
    if not hits:
        return f"No text files under {where} contain {text!r}."
    return f"Found {len(hits)} files containing {text!r}: " + "; ".join(hits)


def open_directory(path):
    """Open a directory in File Explorer by its full path — 'C:/Users/me/Documents',
    'D:/Codes', '~/Downloads'. Use this when the user names a specific location rather than
    a known folder like 'downloads' or 'documents'."""
    full = _resolve(path)
    if not os.path.isdir(full):
        return f"There's no directory at {full}."
    files.open_file(full)
    context.folder = full
    return f"Opened the directory {full}."


def list_drives():
    """List the drives on this computer — C:, D:, and any others — with how much space each
    has free. Use when the user asks what drives exist or where their files might be."""
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.isdir(root):
            try:
                total, _, free = shutil.disk_usage(root)
                drives.append(f"{root} ({free // (2**30)} GB free of {total // (2**30)} GB)")
            except OSError:
                drives.append(f"{root} (unreadable)")
    if not drives:
        return "I couldn't find any drives."
    return "Drives: " + "; ".join(drives)


def file_info(name, kind="any"):
    """Get details about a file — its full path, size, type and last-modified date. Use when
    the user asks how big a file is, when it was changed, or where exactly it lives."""
    import datetime
    direct = _existing_file(name)
    kinds, error = _kinds_for(kind)
    if error:
        return error
    hits = ([(files.EXT_KIND.get(os.path.splitext(direct)[1].lower(), "file"),
              os.path.splitext(os.path.basename(direct))[0], direct)] if direct else
            [(k, n, p) for k in kinds for n, p in files.matches(k, name)])
    if not hits:
        return f"No file matching {name}."
    if len(hits) > 1:
        listed = "; ".join(f"{n} ({k})" for k, n, p in hits[:10])
        return f"{len(hits)} files match: {listed}. Ask which one, then call file_info again."
    _, found_name, path = hits[0]
    try:
        stat = os.stat(path)
        size = stat.st_size
        modified = datetime.datetime.fromtimestamp(stat.st_mtime)
        if size >= 2**30:
            size_str = f"{size / 2**30:.1f} GB"
        elif size >= 2**20:
            size_str = f"{size / 2**20:.1f} MB"
        elif size >= 2**10:
            size_str = f"{size / 2**10:.1f} KB"
        else:
            size_str = f"{size} bytes"
        return (f"{found_name}: {size_str}, last modified {modified:%d %B %Y at %I:%M %p}, "
                f"at {path}")
    except OSError as e:
        return f"Couldn't read info for {path}: {e.strerror or e}"


def open_file(name, kind="any"):
    """Open a file by name in its default application. If several match, they are listed
    rather than guessed — ask which one, then call again with a fuller name."""
    direct = _existing_file(name)
    kinds, error = _kinds_for(kind)
    if error:
        return error
    hits = ([(files.EXT_KIND.get(os.path.splitext(direct)[1].lower(), "file"),
              os.path.splitext(os.path.basename(direct))[0], direct)] if direct else
            [(k, n, p) for k in kinds for n, p in files.matches(k, name)])
    if not hits:
        return f"No file matching {name}."
    if len(hits) > 1:
        listed = "; ".join(f"{n} ({k})" for k, n, p in hits[:10])
        return f"{len(hits)} files match: {listed}. Ask which one, then call open_file again."
    _, found_name, path = hits[0]
    try:
        files.open_file(path)
    except OSError as e:
        return f"Couldn't open {found_name}: {e.strerror or e}"
    context.file = path
    return f"Opened {found_name} from {os.path.dirname(path)}."


def list_folder_contents(folder_name, kind="any"):
    """List the files of one kind sitting directly inside a folder. kind: music, video,
    image, document, or any."""
    path = system.folder(folder_name)
    if not path:
        found = files.folder_matches(folder_name)
        path = found[0][1] if found else None
    if not path:
        return f"Couldn't find a folder called {folder_name}."
    kinds, error = _kinds_for(kind)
    if error:
        return error
    items = [(k, n) for k in kinds for n, _ in files.in_folder(path, k)]
    context.folder = path
    if not items:
        return f"No {kind} files in {path}."
    return (f"{len(items)} files in {path}: " +
            "; ".join(f"{n} ({k})" for k, n in items[:30]))


def read_file(path, lines=200):
    """Read a text file and return its contents — notes, code, config, logs, csv.
    path: a full path, or ~/Documents/notes.txt. lines: how many lines to read back.
    Use run_bash with grep when you need to search inside many files instead of one."""
    full = _resolve_read(path)
    if not os.path.isfile(full):
        return f"There's no file at {full}."
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            read = [next(handle, None) for _ in range(int(lines))]
    except OSError as e:
        return f"Couldn't read {full}: {e.strerror or e}"
    text = "".join(part for part in read if part)
    if not text.strip():
        return f"{full} is empty."
    return f"{full}:\n{text[:TEXT_LIMIT]}"


def write_file(path, text, overwrite=True, directory=""):
    """Create a file, or replace everything in one. In all-access mode (the default) it
    writes at once; with WILCO_ALWAYS_ACT=0 it won't write until you agree.
    path: a bare file name (e.g. "app" or "Main") is written into the folder Wilco is
    currently working in, and when it has no extension one is inferred from the code
    language it names ("app" with Python -> app.py, "Main" with Java -> Main.java). A
    full path is used as given. The old contents are kept as a .bak file, so an
    overwrite can be undone. directory: a folder to write a bare name into instead of
    the current one. overwrite: set to false to refuse clobbering an existing file."""
    folder = _resolve(directory) if directory else None
    full = _resolve_write(path, text, folder)
    if not full:
        return "Give a file name or path to write."
    if not overwrite and os.path.isfile(full):
        return (f"{full} already exists, so I left it alone — pass overwrite=true to "
                f"replace it.")
    what = "replace everything in" if os.path.isfile(full) else "create"
    return _park(f"{what} {full} with {len(text)} characters of text",
                 lambda: _write(full, text))


def edit_file(path, find, replace):
    """Change some text inside a file, leaving the rest alone — fix a typo, change a setting,
    update a value. In all-access mode (the default) it runs at once; with
    WILCO_ALWAYS_ACT=0 it parks and says how many places would change, so a find-and-replace
    can't quietly rewrite more than expected. The old version is kept as a .bak file."""
    full = _resolve_read(path)
    if not os.path.isfile(full):
        return f"There's no file at {full}."
    try:
        original = open(full, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return f"Couldn't read {full}: {e.strerror or e}"
    hits = original.count(find)
    if not hits:
        return f"{full} doesn't contain that text, so there's nothing to change."
    preview = replace[:60] + ("..." if len(replace) > 60 else "")
    return _park(
        f"change {hits} place{'s' if hits > 1 else ''} in {os.path.basename(full)} "
        f"from {find[:60]!r} to {preview!r}",
        lambda: _write(full, original.replace(find, replace)))


def manage_file(action, source, destination=""):
    """Move, copy or rename a file or folder, or make a new folder.
    action: move, copy, rename, new_folder. source: a full path, or a name find_files would
    turn up. destination: where it goes; for rename just the new name; unused for new_folder.
    Never overwrites — if the destination exists it refuses. delete_file first to replace."""
    action = (action or "").strip().lower()
    if action not in ("move", "copy", "rename", "new_folder"):
        return f"{action!r} isn't one of: move, copy, rename, new_folder."
    full = _resolve(source)
    if action == "new_folder":
        return _new_folder(full)
    if not os.path.exists(full):
        found = files.matches("document", source) or files.matches("image", source)
        hint = f" Did you mean {found[0][1]}?" if found else ""
        return f"There's nothing at {full}.{hint} Use find_files to get the real path."
    if not destination:
        return f"{action} needs a destination — where should {os.path.basename(full)} go?"
    target = _destination_for(action, full, destination)
    if os.path.exists(target):
        return (f"{target} already exists, so nothing was touched. Delete it first if the "
                f"user really wants it replaced.")
    return _carry_out(action, full, target)


def delete_file(name, kind="any"):
    """Delete a file. ALWAYS goes to the recycle bin, never a hard delete. In all-access mode
    (the default) it moves it straight to the bin; with WILCO_ALWAYS_ACT=0 it parks first.
    Relay the question, then confirm_yes only if they agree.
    name: a full path, a relative path, or a name find_files would turn up.
    A known path is authoritative, so just-created files that aren't in the disk index yet
    are still found here — no fall-through to a shell delete."""
    direct = _existing_file(name) or _resolve(name)
    if os.path.isfile(direct):
        found_name = os.path.basename(direct)
        return _park(f"move {found_name} to the recycle bin (from {os.path.dirname(direct)})",
                     lambda: shell.recycle(direct))
    kinds = KINDS if kind in ("any", "", None) else (kind,)
    hits = [(k, n, p) for k in kinds for n, p in files.matches(k, name)]
    if not hits:
        return f"No file matching {name}, so there's nothing to delete."
    if len(hits) > 1:
        listed = "; ".join(f"{n} ({k}) in {os.path.dirname(p)}" for k, n, p in hits[:10])
        return f"{len(hits)} files match: {listed}. Ask exactly which one before deleting."
    _, found_name, path = hits[0]
    return _park(f"move {found_name} to the recycle bin (from {os.path.dirname(path)})",
                 lambda: shell.recycle(path))
