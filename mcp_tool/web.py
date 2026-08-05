"""Everything Wilco fetches from the internet.

Search and page reading, Wikipedia, weather, news, dictionary, exchange rates, crypto prices,
and YouTube playback. Every source here is keyless on purpose: no signup, no API key to rotate
or leak, nothing to expire silently months later. DuckDuckGo's HTML endpoint and Wikipedia's
API need no credentials, and wttr.in, dictionaryapi.dev, open.er-api.com and CoinGecko all
serve anonymous requests — so this whole module works on a fresh clone with an empty .env.
"""
import html
import re
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET

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


# DuckDuckGo puts paid results in the same result__a markup as real ones, so scraping the
# page hands back Jobrapido before it hands back anything true. An advert is not an answer,
# and a model given nothing but adverts fills the silence with something plausible instead.
_ADVERT = re.compile(r"duckduckgo\.com/y\.js|[?&]ad_(?:domain|provider|type)=|/aclick\?")


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
    kept = [(url, _text(title), _text(snippets[i]) if i < len(snippets) else "")
            for i, (href, title) in enumerate(links)
            if not _ADVERT.search(url := _real_url(href))]
    if not kept:
        return (f"Nothing but adverts came back for {query}. Say that you couldn't find a real "
                f"answer and offer to try different wording — do NOT invent one.")
    lines = [f"Search results for {query}:"]
    for i, (url, title, body) in enumerate(kept[:int(count)], 1):
        lines.append(f"{i}. {title}\n   {body}\n   {url}")
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


WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_REST = "https://en.wikipedia.org/api/rest_v1/page/summary/"
# Wikimedia asks for a descriptive agent rather than a spoofed browser one, and rate-limits
# generic strings harder
WIKI_HEADERS = {"User-Agent": "Wilco/1.0 (personal voice assistant)",
                "Accept-Language": "en"}


def _wiki_search(query, limit=5):
    """Article titles matching free text. This is what lets a spoken question find a page."""
    try:
        data = requests.get(WIKI_API, headers=WIKI_HEADERS, timeout=20, params={
            "action": "query", "list": "search", "srsearch": query,
            "srlimit": limit, "format": "json"}).json()
    except (requests.RequestException, ValueError):
        return []
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def _wiki_page(title):
    """The REST summary blob for an exact title, or None."""
    url = WIKI_REST + urllib.parse.quote(title.strip().replace(" ", "_"), safe="")
    try:
        reply = requests.get(url, headers=WIKI_HEADERS, timeout=20)
    except requests.RequestException:
        return None
    if reply.status_code != 200:
        return None
    data = reply.json()
    return None if data.get("type", "").endswith("disambiguation") else data


def wikipedia_summary(topic, sentences=3):
    """What Wikipedia says about something — a person, place, event, thing, idea. The first
    choice for 'tell me about X', 'who is X', 'what is X'.

    The topic does not have to be an exact article title: a spoken question like 'who invented
    the telephone' is searched for and the best matching article is used. sentences: how much
    detail, 2-5 sounds natural aloud. For more than the opening, use wikipedia_article."""
    topic = topic.strip()
    page = _wiki_page(topic)
    others = ""
    if page is None:
        titles = _wiki_search(topic)
        if not titles:
            return f"Wikipedia has nothing for {topic}. Try web_search instead."
        page = _wiki_page(titles[0])
        if page is None:
            return (f"{topic} matches several Wikipedia articles — {', '.join(titles[:4])}. "
                    f"Ask the user which one they meant.")
        # a spoken question rarely names an article, so say what else matched in case the
        # top hit answered a different question from the one that was asked
        if len(titles) > 1:
            others = f" Other articles that matched: {', '.join(titles[1:4])}."
    extract = (page.get("extract") or "").strip()
    if not extract:
        return "That Wikipedia page has no summary text. Try wikipedia_article."
    parts = re.split(r"(?<=[.!?])\s+", extract)
    said = " ".join(parts[:max(1, int(sentences))])
    more = " More in wikipedia_article if they want it." if len(parts) > int(sentences) else ""
    return f"{page.get('title', topic)}: {said}{more}{others}"


def wikipedia_article(topic, section="", limit=3000):
    """The fuller Wikipedia article when the summary isn't enough — history, details, a
    specific part. section: the heading to read, like 'History' or 'Early life'; leave empty
    for the opening plus a list of the sections available, then ask which one interests them.
    Summarise what comes back in your own words; never read it out verbatim."""
    topic = topic.strip()
    try:
        data = requests.get(WIKI_API, headers=WIKI_HEADERS, timeout=25, params={
            "action": "query", "prop": "extracts", "explaintext": 1,
            "exsectionformat": "wiki", "titles": topic, "redirects": 1,
            "format": "json"}).json()
        pages = list(data.get("query", {}).get("pages", {}).values())
    except (requests.RequestException, ValueError, AttributeError) as e:
        return f"Couldn't reach Wikipedia: {e}"

    text = (pages[0].get("extract") or "").strip() if pages else ""
    if not text:
        titles = _wiki_search(topic)
        if not titles:
            return f"Wikipedia has no article for {topic}."
        return f"No exact article for {topic}. Closest: {', '.join(titles[:4])}. Ask which."

    # "== History ==" markers split the article; the first chunk is the untitled opening
    chunks = re.split(r"\n==\s*([^=]+?)\s*==\n", "\n" + text)
    opening, headings = chunks[0].strip(), chunks[1::2]
    if section.strip():
        wanted = section.strip().lower()
        for name, body in zip(headings, chunks[2::2]):
            if wanted in name.lower():
                return f"{topic} — {name}: {body.strip()[:int(limit)]}"
        return (f"{topic} has no section called {section}. It has: "
                f"{', '.join(headings[:15])}. Ask which one.")
    listed = f" Sections available: {', '.join(headings[:15])}." if headings else ""
    return f"{topic}: {opening[:int(limit)]}{listed}"


def weather(city="", when="now"):
    """Current weather and today's outlook for a place. city: a name like Delhi or London —
    leave empty for wherever this machine is. when: 'now' or 'today'. Say the numbers in a
    natural way, and mention what it feels like when that differs from the actual figure."""
    place = city.strip() or ""
    url = f"https://wttr.in/{urllib.parse.quote(place)}?format=j1"
    try:
        data = requests.get(url, headers=HEADERS, timeout=25).json()
    except (requests.RequestException, ValueError) as e:
        return f"Couldn't get the weather: {e}"
    now = data["current_condition"][0]
    where = place or (data.get("nearest_area", [{}])[0]
                      .get("areaName", [{}])[0].get("value", "here"))
    described = now["weatherDesc"][0]["value"]
    line = (f"{where}: {now['temp_C']}C, {described.lower()}, feels like "
            f"{now['FeelsLikeC']}C, humidity {now['humidity']}%, "
            f"wind {now['windspeedKmph']} km/h.")
    if when.strip().lower() == "today" and data.get("weather"):
        today = data["weather"][0]
        line += (f" Today: high {today['maxtempC']}C, low {today['mintempC']}C, "
                 f"{today.get('hourly', [{}])[4].get('chanceofrain', '0')}% chance of rain.")
    return line


def news_headlines(topic="", count=6):
    """Today's news headlines. topic: leave empty for the main headlines, or give a subject
    like cricket, technology, business. Read a few out conversationally — don't list all of
    them like a menu, and offer to go deeper on any one."""
    if topic.strip():
        url = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote_plus(topic.strip()) + "&hl=en-IN&gl=IN&ceid=IN:en")
    else:
        url = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
    try:
        raw = requests.get(url, headers=HEADERS, timeout=20).content
        items = ET.fromstring(raw).findall(".//item")
    except (requests.RequestException, ET.ParseError) as e:
        return f"Couldn't fetch the news: {e}"
    if not items:
        return f"No headlines found{' for ' + topic if topic else ''}."
    lines = []
    for item in items[:int(count)]:
        title = (item.findtext("title") or "").strip()
        # Google appends " - Publisher"; keep it, it's worth saying who reported it
        if title:
            lines.append(title)
    heading = f"Top headlines{' about ' + topic if topic else ''}:"
    return heading + "\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(lines, 1))


def define(word):
    """What a word means, how it's pronounced, and an example of it in use. For 'what does X
    mean', 'define X', 'how do you spell X'. Give the plain sense first, not every entry."""
    url = "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(word.strip())
    try:
        reply = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        return f"Couldn't reach the dictionary: {e}"
    if reply.status_code == 404:
        return f"No dictionary entry for {word}. It may be a name or a misspelling."
    try:
        entry = reply.json()[0]
    except (ValueError, IndexError, KeyError):
        return f"The dictionary gave nothing usable for {word}."
    lines = [f"{entry.get('word', word)}"]
    for meaning in entry.get("meanings", [])[:3]:
        first = (meaning.get("definitions") or [{}])[0]
        part = meaning.get("partOfSpeech", "")
        lines.append(f"({part}) {first.get('definition', '').strip()}")
        if first.get("example"):
            lines[-1] += f"  e.g. {first['example']}"
    return " — ".join(lines)


def convert_currency(amount, source, target):
    """Convert money between real-world currencies, with today's rate. source and target are
    three-letter codes — USD, INR, EUR, GBP, JPY. Say the result naturally, and mention the
    rate only if they ask. For Bitcoin and other coins use crypto_price instead."""
    source, target = source.strip().upper(), target.strip().upper()
    try:
        value = float(str(amount).replace(",", "").strip())
    except ValueError:
        return f"{amount} isn't a number I can convert."
    try:
        data = requests.get(f"https://open.er-api.com/v6/latest/{source}",
                            headers=HEADERS, timeout=20).json()
    except (requests.RequestException, ValueError) as e:
        return f"Couldn't get exchange rates: {e}"
    if data.get("result") != "success":
        return f"{source} isn't a currency code I recognise."
    rate = data.get("rates", {}).get(target)
    if rate is None:
        return f"No rate for {source} to {target}."
    return (f"{value:,.2f} {source} is {value * rate:,.2f} {target} "
            f"(1 {source} = {rate:,.4f} {target}, as of {data.get('time_last_update_utc', '')[:16]}).")


def crypto_price(coin="bitcoin", currency="inr"):
    """The current price of a cryptocurrency. coin: the full name — bitcoin, ethereum,
    dogecoin, solana — not the ticker. currency: inr, usd, eur. Mention the day's move, since
    a price on its own says little."""
    coin, currency = coin.strip().lower().replace(" ", "-"), currency.strip().lower()
    try:
        data = requests.get("https://api.coingecko.com/api/v3/simple/price",
                            headers=HEADERS, timeout=20,
                            params={"ids": coin, "vs_currencies": currency,
                                    "include_24hr_change": "true"}).json()
    except (requests.RequestException, ValueError) as e:
        return f"Couldn't get the price: {e}"
    if not data.get(coin):
        return (f"No coin called {coin}. Use the full name — bitcoin, not BTC — or check the "
                f"spelling.")
    price = data[coin].get(currency)
    if price is None:
        return f"No {currency.upper()} price for {coin}."
    change = data[coin].get(f"{currency}_24h_change")
    moved = f", {'up' if change >= 0 else 'down'} {abs(change):.1f}% today" if change else ""
    return f"{coin.replace('-', ' ').title()} is {price:,.2f} {currency.upper()}{moved}."


def open_website(url):
    """Open a URL in the default browser. url: a full address, or a bare domain like bbc.com."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url} in the browser."
