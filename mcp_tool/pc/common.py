"""Shared helpers for pc_* modules — path resolution, kind mapping, backups.

This is not a tool module itself (no public tools); the four pc_* modules
import from here. It must not import any pc_* module to avoid cycles.
"""
import os
import re
import shutil

import windows.files as files
import windows.shell as shell
from core import context

KINDS = ("music", "video", "image", "document")

TEXT_EXTS = {".txt", ".md", ".py", ".json", ".csv", ".log", ".ini", ".cfg", ".conf",
             ".yaml", ".yml", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".java",
             ".c", ".cpp", ".h", ".sh", ".bat", ".ps1", ".toml", ".env", ".gitignore"}
SKIP_DIRS = {"node_modules", "site-packages", ".git", "__pycache__", "venv", ".venv",
             "appdata", "windows", "program files", "program files (x86)", "$recycle.bin"}

_CODE_PATTERNS = [
    (".py",    r"(?m)^\s*(?:import\s+\w+|from\s+\w+\s+import|def\s+\w+\s*\(|class\s+\w+\s*:)"),
    (".ts",    r"(?m)\b(?:interface|type)\s+\w+[:,]|:\s*(?:string|number|boolean|any|unknown)\b"),
    (".js",    r"(?m)\b(?:const|let|var)\s+\w+\s*=|console\.log\(|=>\s*\{|require\s*\("),
    (".cs",   r"(?m)\busing\s+System(?:\.|;\s*)?|Console\.|static\s+void\s+Main"),
    (".java",  r"(?m)\b(?:public|private|protected)\s+(?:static\s+)?(?:class|interface|void|int|String)\b|(?:^|[\s;}])(?:class|interface)\s+\w+\s*\{"),
    (".go",    r"(?m)^\s*package\s+\w+\s*$|\bfunc\s+\w+\s*\("),
    (".rs",    r"(?m)^\s*(?:fn\s+\w+\s*\(|use\s+[\w:]+::|let\s+(?:mut\s+)?\w+)"),
    (".cpp",   r"(?m)(?:#\s*include\s*<iostream>|\bstd\s*::|using\s+namespace\s+\w+)"),
    (".c",     r"(?m)(?:\bint\s+main\s*\(|#\s*include\s*<[\w.]+>)"),
    (".php",   r"(?m)<\?php"),
    (".rb",    r"(?m)^\s*(?:def\s+\w+|require\s+['\"]\w+|puts\s+['\"]|class\s+\w+\s*$)"),
    (".pl",    r"(?m)\b(?:use\s+strict;|use\s+warnings;|my\s+\$\w+|sub\s+\w+\s*\{)"),
    (".swift", r"(?m)^\s*(?:import\s+(?:Foundation|UIKit)\b|func\s+\w+\s*\(|struct\s+\w+\s*\{)"),
    (".kt",    r"(?m)^\s*(?:fun\s+\w+\s*\(|class\s+\w+\s*\{|\bval\s+\w+\s*=|\bvar\s+\w+\s*=)"),
    (".bash",  r"(?m)^\s*(?:#\s*!.*\b(?:bash|sh)\b|if\s+\[|while\s+(?:read|true)\b|echo\s+\$+\w+)"),
    (".ps1",   r"(?m)^\s*(?:Write-Host|Get-Process|Set-Content|Export-Csv|param\s*\(|function\s+\w+\s*\{)"),
    (".sql",   r"(?im)^\s*(?:select\b|insert\s+into|update\s+\w+|delete\s+from|create\s+table)"),
    (".html",  r"(?mi)^\s*<(?:!DOCTYPE\s+html|html\b|body\b|head\b)>"),
    (".css",   r"(?m)^\s*[.#][\w-]+\s*\{"),
    (".json",  r"(?m)^\s*\{\s*\"[^\"]+\"\s*:"),
    (".md",    r"(?m)^\s*#{1,6}\s+\S+"),
]


def _normalise_kind(kind):
    value = str(kind or "any").strip().lower().lstrip(".")
    aliases = {
        "": "any", "any": "any", "file": "any", "files": "any",
        "music": "music", "audio": "music", "song": "music", "songs": "music",
        "video": "video", "videos": "video",
        "image": "image", "images": "image", "photo": "image", "photos": "image",
        "picture": "image", "pictures": "image", "screenshot": "image",
        "document": "document", "documents": "document", "doc": "document", "docs": "document",
    }
    return aliases.get(value, files.EXT_KIND.get("." + value, value))


def _kinds_for(kind):
    normalised = _normalise_kind(kind)
    if normalised == "any":
        return KINDS, None
    if normalised not in KINDS:
        return (), f"kind must be one of: any, {', '.join(KINDS)}."
    return (normalised,), None


def _resolve(path):
    path = os.path.expanduser(path.strip().strip('"'))
    if re.fullmatch(r"/[a-zA-Z]/.*", path):
        path = path[1] + ":" + path[2:]
    return os.path.abspath(path)


def _existing_file(value):
    if not isinstance(value, str):
        return None
    candidate = _resolve(value)
    return candidate if os.path.isfile(candidate) else None


def _working_dir():
    """The directory file-producing tools run in by default.
    context.folder is set when the user explicitly points Wilco at a folder
    ('open my documents', 'go to D:/Projects', ...); otherwise it is the
    directory the user launched Wilco from — so a fresh clone just works
    where they are, without Wilco parking files in its own folder."""
    if context.folder:
        return context.folder
    return os.getcwd()


def _infer_extension(content):
    for ext, pattern in _CODE_PATTERNS:
        if re.search(pattern, content):
            return ext
    return ""


def _resolve_write(name, text, folder=None):
    name = (name or "").strip().strip('"')
    if not name:
        return ""
    if os.path.isabs(name) or name.startswith("~") or re.match(r"^[a-zA-Z]:", name):
        return _resolve(name)
    work = folder or _working_dir()
    full = os.path.join(work, name)
    if os.path.splitext(os.path.basename(full))[1]:
        return full
    ext = _infer_extension((text or "")[:600])
    return full + ext if ext else full


def _resolve_read(path):
    full = _resolve(path)
    if os.path.isfile(full):
        return full
    name = (path or "").strip().strip('"')
    if os.path.isabs(name) or name.startswith("~") or re.match(r"^[a-zA-Z]:", name):
        return full
    candidate = os.path.join(_working_dir(), name)
    if os.path.isfile(candidate):
        return candidate
    if not os.path.splitext(name)[1]:
        for ext in (e for e, _ in _CODE_PATTERNS):
            match = os.path.join(_working_dir(), name + ext)
            if os.path.isfile(match):
                return match
    return full


def _text_files(where):
    for root, dirs, names in os.walk(where):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(("$", "."))]
        for name in names:
            if os.path.splitext(name)[1].lower() in TEXT_EXTS:
                yield os.path.join(root, name)


def _holds(path, needle):
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            return needle in handle.read().lower()
    except (OSError, UnicodeDecodeError):
        return False


def _backup(full):
    if os.path.isfile(full):
        try:
            shutil.copy2(full, full + ".bak")
            return " The previous version is saved alongside it as a .bak file."
        except OSError:
            return " I couldn't make a backup copy, so the old contents will be lost."
    return ""


def _write(full, text):
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    note = _backup(full)
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(text)
    return f"Saved {len(text)} characters to {full}.{note}"


def _new_folder(full):
    if os.path.exists(full):
        return f"{full} already exists."
    try:
        os.makedirs(full)
    except OSError as e:
        return f"Couldn't create {full}: {e.strerror or e}"
    return f"Created the folder {full}."


def _destination_for(action, full, destination):
    target = _resolve(destination)
    if action == "rename" or os.path.isdir(os.path.dirname(target)) and not os.path.isdir(target):
        if os.sep in destination or ":" in destination:
            return target
        return os.path.join(os.path.dirname(full), destination)
    if os.path.isdir(target):
        return os.path.join(target, os.path.basename(full))
    return target


def _carry_out(action, full, target):
    try:
        if action == "copy":
            shutil.copytree(full, target) if os.path.isdir(full) else shutil.copy2(full, target)
        else:
            shutil.move(full, target)
    except OSError as e:
        return f"Couldn't {action} {full}: {e.strerror or e}"
    done = {"move": "Moved", "copy": "Copied", "rename": "Renamed"}[action]
    return f"{done} {os.path.basename(full)} to {target}."


def _wifi_password_text():
    value = shell.wifi_password()
    return f"The Wi-Fi password is {value}." if value else "Couldn't read that password."
