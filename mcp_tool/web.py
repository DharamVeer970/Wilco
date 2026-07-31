"""Web search, page reading, and YouTube playback.

DuckDuckGo's HTML endpoint needs no key and no browser driver — the same approach
core/online.py already uses for YouTube, so nothing new gets installed for this.
"""
import html
import re
import urllib.parse
import webbrowser

import requests

from core import context, online

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "Accept-Language": "en-US,en"}
TAG = re.compile(r"<[^>]+>")
DROP = re.compile(r"<(script|style|nav|header|footer)\b.*?</\1>", re.S | re.I)
SITES = {"google": "https://www.google.com/search?q={}",
         "youtube": "https://www.youtube.com/results?search_query={}",
         "wikipedia": "https://en.wikipedia.org/w/index.php?search={}",
         "maps": "https://www.google.com/maps/search/{}",
         "amazon": "https://www.amazon.in/s?k={}",
         "github": "https://github.com/search?q={}"}


def _text(chunk):
    return " ".join(html.unescape(TAG.sub(" ", chunk)).split())


def _real_url(href):
    """DDG wraps every result in a redirect — unwrap it to the actual destination."""
    found = re.search(r"uddg=([^&]+)", href)
    return urllib.parse.unquote(found.group(1)) if found else href


def web_search(query, count=5):
    """Search the web and read back the top results. Use this whenever you are asked about
    news, current events, prices, scores, releases, or any fact you are not certain of.
    Answer from the results — do not guess. query: the search terms. count: how many results."""
    try:
        page = requests.post("https://html.duckduckgo.com/html/", data={"q": query},
                             headers=HEADERS, timeout=20).text
    except requests.RequestException as e:
        return f"The search didn't go through: {e}"
    links = re.findall(r'result__a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)
    snippets = re.findall(r'result__snippet[^>]*>(.*?)</a>', page, re.S)
    if not links:
        return f"No results for {query}."
    lines = [f"Search results for {query}:"]
    for i, (href, title) in enumerate(links[:int(count)]):
        body = _text(snippets[i]) if i < len(snippets) else ""
        lines.append(f"{i + 1}. {_text(title)}\n   {body}\n   {_real_url(href)}")
    return "\n".join(lines)


def read_web_page(url, limit=4000):
    """Fetch one web page and return its readable text. Use after web_search when a result
    looks right but the snippet is too short to answer properly."""
    try:
        page = requests.get(url, headers=HEADERS, timeout=20).text
    except requests.RequestException as e:
        return f"Couldn't open that page: {e}"
    body = _text(DROP.sub(" ", page))
    return body[:int(limit)] or "That page had no readable text."


def search_in_browser(query, site="google"):
    """Open a search results page in the browser so the user can look at it themselves.
    Use this when they say to search ON a site, or want to see results rather than hear them.
    site: google, youtube, wikipedia, maps, amazon or github."""
    site = site.lower().strip()
    if site not in SITES:
        return f"I can only search {', '.join(SITES)}."
    context.query = query
    webbrowser.open(SITES[site].format(urllib.parse.quote_plus(query)))
    return f"Opened a {site} search for {query} in the browser."


def play_on_youtube(query):
    """Search YouTube and immediately start playing the top hit in the browser. This is the
    tool for 'play <anything> on youtube' — it plays, it does not just open a results page."""
    hits = online.search(query)
    if not hits:
        return f"Nothing came up on YouTube for {query}."
    context.remember_search(query, hits)
    title, video_id = context.step(1)
    online.play(video_id)
    others = "; ".join(t[:50] for t, _ in hits[1:4])
    return f"Now playing: {title}. Also found: {others}"


def play_next_result(direction="next"):
    """Move to the next or previous video from the last YouTube search and play it.
    Use for 'play the next one', 'go back', 'skip this'. direction: next or previous."""
    hit = context.step(-1 if direction.lower().startswith("prev") else 1)
    if not hit:
        return "That's the end of the list — nothing further that way."
    title, video_id = hit
    online.play(video_id)
    return f"Now playing: {title}"


def open_website(url):
    """Open a URL in the default browser. url: a full address, or a bare domain like bbc.com."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url} in the browser."
