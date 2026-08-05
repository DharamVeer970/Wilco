import os
import re
import string
from functools import lru_cache

from rapidfuzz import fuzz, process

from config import FUZZ_MIN, roots

HOME = os.path.expanduser("~").lower()

KINDS = {
    "music": (".mp3", ".wav", ".m4a", ".flac", ".wma", ".aac", ".ogg", ".opus"),
    "video": (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v"),
    "image": (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg"),
    "document": (".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".txt", ".csv"),
}
EXT_KIND = {ext: kind for kind, exts in KINDS.items() for ext in exts}

# system and package folders — pruned for speed, and to skip bundled sample media
SKIP = {
    "windows", "program files", "program files (x86)", "programdata", "$recycle.bin",
    "appdata", "node_modules", "site-packages", "venv", ".venv", ".git",
    "system volume information", "temp", "cache", "__macosx",
}
USERS_ROOT = os.path.dirname(HOME)


def _keep(dirpath, dirnames):
    """Drop system junk, and other people's profiles — those aren't your folders."""
    kept = []
    for d in dirnames:
        if d.lower() in SKIP or d.startswith(("$", ".")):
            continue
        full = os.path.join(dirpath, d).lower()
        if os.path.dirname(full) == USERS_ROOT and full != HOME:
            continue
        kept.append(d)
    return kept


def _clean(stem):
    return re.sub(r"\s{2,}", " ", stem.replace("_", " ")).strip()


def _roots():
    """WILCO_ROOT (';'-separated) if set, else every drive — measured at ~3s for C: and D:."""
    pinned = [p for p in roots().split(";") if os.path.isdir(p)]
    return pinned or [f"{d}:\\" for d in string.ascii_uppercase if os.path.isdir(f"{d}:\\")]


@lru_cache(maxsize=1)
def _scan():
    """({kind: [(name, path)]}, [(folder name, path)]) — one walk for both, cached per session."""
    found = {kind: [] for kind in KINDS}
    folders = []
    for root in _roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = _keep(dirpath, dirnames)
            folders.extend((d, os.path.join(dirpath, d)) for d in dirnames)
            for f in filenames:
                stem, ext = os.path.splitext(f)
                kind = EXT_KIND.get(ext.lower())
                if kind:
                    found[kind].append((_clean(stem), os.path.join(dirpath, f)))
    return ({k: sorted(v, key=lambda s: s[0].lower()) for k, v in found.items()},
            sorted(folders, key=lambda s: s[0].lower()))


def library(kind):
    """[(display name, path)] for one kind. First call scans the machine."""
    return _scan()[0][kind]


def _rank(item):
    """Shortest name, then yours over a backup copy, then shallowest path."""
    name, path = item
    return (len(name), not path.lower().startswith(HOME), path.count(os.sep), len(path))


def folder_matches(spoken, limit=5):
    """Every folder matching a spoken name, likeliest first — caller asks when several."""
    spoken = spoken.strip().lower()
    if not spoken:
        return []
    items = _scan()[1]
    exact = [s for s in items if s[0].lower() == spoken]
    if exact:
        return sorted(exact, key=_rank)[:limit]
    word = re.compile(rf"\b{re.escape(spoken)}", re.I)
    hits = [s for s in items if word.search(s[0])]
    if hits:
        return sorted(hits, key=_rank)[:limit]
    scored = process.extract(spoken, [s[0].lower() for s in items],
                             scorer=fuzz.ratio, score_cutoff=FUZZ_MIN, limit=limit)
    return [items[i] for _, _, i in scored]


def in_folder(path, kind):
    """[(display name, path)] of one kind directly inside a folder."""
    try:
        return sorted(
            (_clean(os.path.splitext(e.name)[0]), e.path)
            for e in os.scandir(path)
            if e.is_file() and os.path.splitext(e.name)[1].lower() in KINDS[kind]
        )
    except OSError:  # PermissionError and FileNotFoundError are both OSError
        return []


def matches(kind, spoken, limit=5):
    """Every file whose name starts a word with the spoken text — for asking which."""
    spoken = spoken.strip().lower()
    if not spoken:
        return []
    word = re.compile(rf"\b{re.escape(spoken)}", re.I)
    return sorted((s for s in library(kind) if word.search(s[0])), key=lambda s: len(s[0]))[:limit]


def find(kind, spoken, fuzzy=True):
    """Best (name, path) for spoken text or a 1-based number, or None."""
    items = library(kind)
    if not items:
        return None
    spoken = spoken.strip().lower()
    number = re.fullmatch(r"(?:number\s+|no\.?\s+)?(\d{1,4})", spoken)
    if number:
        i = int(number.group(1)) - 1
        return items[i] if 0 <= i < len(items) else None
    word = re.compile(rf"\b{re.escape(spoken)}", re.I)
    hits = [s for s in items if word.search(s[0])]
    if hits:
        return min(hits, key=lambda s: len(s[0]))
    if fuzzy:
        names = [s[0].lower() for s in items]
        best = process.extractOne(spoken, names, scorer=fuzz.ratio, score_cutoff=FUZZ_MIN)
        if best:
            return items[best[2]]
    return None


def open_file(path):
    os.startfile(path)
