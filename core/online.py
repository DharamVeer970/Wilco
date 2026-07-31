import json
import urllib.parse
import webbrowser

import requests

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en"}


def _initial_data(page):
    """The ytInitialData blob, parsed. None if YouTube changed the page shape."""
    start = page.find("ytInitialData")
    brace = page.find("{", start) if start != -1 else -1
    if brace == -1:
        return None
    try:
        return json.JSONDecoder().raw_decode(page, brace)[0]
    except ValueError:
        return None


def _videos(node):
    """Every node holding both a videoId and a title, so the two always belong together."""
    if isinstance(node, dict):
        if "videoId" in node and "title" in node:
            yield node
        for value in node.values():
            yield from _videos(value)
    elif isinstance(node, list):
        for value in node:
            yield from _videos(value)


def _title_of(node):
    title = node.get("title")
    if isinstance(title, str):
        return title
    if isinstance(title, dict):
        runs = title.get("runs")
        return runs[0].get("text") if runs else title.get("simpleText")
    return None


def search(query, limit=8):
    """[(title, video_id)] for a YouTube search, top result first."""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    try:
        page = requests.get(url, headers=HEADERS, timeout=20).text
    except requests.RequestException:
        return []
    data = _initial_data(page)
    if data is None:
        return []
    hits, seen = [], set()
    for node in _videos(data):
        vid, title = node["videoId"], _title_of(node)
        if not title or len(vid) != 11 or vid in seen:
            continue
        seen.add(vid)
        hits.append((title, vid))
        if len(hits) == limit:
            break
    return hits


def play(video_id):
    webbrowser.open(f"https://www.youtube.com/watch?v={video_id}&autoplay=1")
