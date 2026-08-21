"""Regexes and lookup tables for the instant command path.

Pure data — no imports of core.* to avoid cycles. Both core/commands.py and
core/commands_steps.py import from here.
"""
import re

SITES = {
    "youtube": "https://www.youtube.com",
    "wikipedia": "https://www.wikipedia.org",
    "google": "https://www.google.com",
}
SEARCH = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={}",
    "maps": "https://www.google.com/maps/search/{}",
    "amazon": "https://www.amazon.in/s?k={}",
    "github": "https://github.com/search?q={}",
}
KIND_WORDS = {
    "music": ("music", "song", "songs", "audio", "playlist"),
    "video": ("video", "videos", "movie", "movies"),
    "image": ("image", "images", "photo", "photos", "picture", "pictures"),
    "document": ("document", "documents", "pdf", "pdfs", "file", "files"),
}
ONLINE = "youtube"
DOWN = re.compile(r"\b(?:down|low|lower|decrease|reduce|less|quieter|softer|dim|dimmer|darker)\b")
BRIGHT = re.compile(r"\b(?:brightness|dim|dimmer|darker|brighten|brighter)\b")
TALK = re.compile(
    r"\b(?:talk|talking|speak|speaking|speech|say|saying|voice|read|reading)\b[\w\s']{0,20}?"
    r"\b(?:speed|pace|rate|fast|faster|quick|quicker|slow|slower|slowly)\b"
    r"|\b(?:speed\s+up|slow\s+down)\b")
SLOWER = re.compile(r"\b(?:slow|slower|slowly|down|less)\b")
COMPOSE = re.compile(
    r"^(?:an?|the|my)?\s*(?:message|msg|text|email|e-?mail|note|reply|sms|whatsapp)\b"
    r"|\b(?:to|in|on)\s+(?:whatsapp|telegram|gmail|outlook|email|discord|slack|teams)\b")
RELATIVE = re.compile(r"\b(?:faster|slower|quicker|slowly|more|less|up|down|bit)\b")
POWER = [
    (r"shut\s?down|turn\s+off|power\s+off", "shutdown"),
    (r"restart|reboot", "restart"),
    (r"lock(?:\s+(?:the|my)\s+screen)?", "lock"),
    (r"(?:go\s+to\s+)?sleep|hibernate|suspend|put\s+\S+(?:\s+\S+)?\s+to\s+sleep", "sleep"),
]
THIS_PC = r"(?:\s+(?:the|my|this))?(?:\s+(?:computer|pc|laptop|system|machine|thing))?"
MEDIA_WORDS = {"pause": "play_pause", "resume": "play_pause", "play_pause": "play_pause",
               "next": "next", "skip": "next", "previous": "previous", "back": "previous",
               "stop": "stop"}
STRIP = " .,!?;:'\""
WHICH = "which one?"
NAME = r"(?:wilco|wilko|will\s?co)"

HINDI = [
    (r"\b(?:aavaaz|awaaz|aawaz|sound|volume)\b.*\bband\b", "mute"),
    (r"\b(?:aavaaz|awaaz|aawaz|sound|volume)\b.*"
     r"\b(?:barhaao|barhao|badhao|tez|zyaada|zyada|ooncha|oopar)\b", "volume up"),
    (r"\b(?:aavaaz|awaaz|aawaz|sound|volume)\b.*"
     r"\b(?:kam|ghataao|ghatao|dheere|neeche)\b", "volume down"),
    (r"\b(?:tez|jaldi|fast)\b.*\bbolo\b", "talk faster"),
    (r"\b(?:dheere|aaraam|slow)\b.*\bbolo\b", "talk slower"),
    (r"\bkitane baje|kitne baje|samay kya|time kya\b", "what is the time"),
    (r"^(?:mera |meri |mere )?(.+?)\s+(?:kholo|khol do|khol|chaaloo karo|chalu karo)\b",
     "open {}"),
    (r"^(?:ise|isko|use|usko|ye|yeh)?\s*(.*?)\s*\bband kar(?:o| do)\b", "close {}"),
]
_HINDI = [(re.compile(pattern), english) for pattern, english in HINDI]
PLAIN = re.compile(r"(?:what'?s?|what is|tell me)\s+the\s+(?:time|date)$", re.I)
RECALL = re.compile(r"what(?:'s| is| was)\s+(?:that|it|this|playing)"
                    r"|what did (?:you play|i search(?: for)?)", re.I)

FILLER = (r"(?:hey|hi|hello|ok|okay|so|now|well|um+|uh+|erm|like|actually|alright|right|"
          r"listen|please|just|kindly|quickly|maybe|then|also|and)")
POLITE = re.compile(
    r"^(?:" + FILLER + r"[\s,]+)*(?:" + NAME + r"[\s,]*)?(?:" + FILLER + r"[\s,]+)*"
    r"(?:(?:can|could|would|will)\s+(?:you|u)\s+)?"
    r"(?:(?:i\s+(?:want|need)\s+(?:you\s+)?to|i'?d\s+like\s+(?:you\s+)?to)\s+)?"
    r"(?:" + FILLER + r"[\s,]+)*")
TRAILING = re.compile(r"(?:[\s,]+(?:please|for\s+me|mate|buddy|bro|now|" + NAME + r"|thanks?))+$")
SPLIT_RE = re.compile(r"\s(?:and then|and also|then|and)\s+")
VERBS = ("open", "show", "play", "search", "google", "find", "type", "write", "set",
         "turn", "go to", "list", "close", "pause", "next", "previous", "stop",
         "mute", "volume", "brightness", "launch", "start")
QUESTION = re.compile(
    r"^(?:what|why|how|when|where|who|which|whose|whom|whats|what's|"
    r"is|are|was|were|do|does|did|should|shall|may|might|"
    r"tell|explain|define|describe|compare|suggest|recommend|think)\b")

STEP = re.compile(r"(?:play|open|go\s+to)?\s*(?:the\s+)?(next|previous|last)\s*(?:one|song|video|track)?")
CLOSE = re.compile(r"close\b(.*)")
WHAT_IS_IT = re.compile(r"what(?:'s| is| was)\s+(?:that|it|this|playing)"
                        r"|what did (?:you play|i search(?: for)?)")
PLAY_IT = re.compile(r"(?:play|resume|open)\s*(?:it|that|this|the\s+same|again)?")
KIND_ASKED = re.compile(r"(?:play|open|show|list|start|listen to)\s+(?:me\s+)?(?:(?:my|all|some|the|a)\s+)?(\w+)")
FILLER_RE = r"(?:this|that|the|current|my|active|open|browser|chrome)"
SCOPE = re.compile(rf"(?:{FILLER_RE}\s+)*(tab|window)s?(?:\s+(?:in|on|of)\s+(?:the\s+|my\s+)?(.+))?$")
ITSELF = ("", "it", "that", "this", "the app", "this app", "the application")
VAGUE = re.compile(r"(?:everything|all|all of (?:it|them)|all (?:the )?(?:apps|windows|tabs))")
QUIT = re.compile(r"(?:" + NAME + r"[ ,]*)?(?:quit|exit|goodbye|bye)")
FRESH = re.compile(r"(?:start over|new task|forget (?:it|that|everything))")
TYPE = re.compile(r"(?:type|write)\s+(.+)")
TYPE_SPOKEN = re.compile(r"(?:type|write)\s+(.+)", re.I)
CODE_WRITE = re.compile(
    r"\b(?:python|typescript|java|javascript|go|golang|rust|swift|kotlin|c\+\+|c#|"
    r"php|perl|lua|bash|shell|powershell|sql|html|css|vba|json)\b"
    r"|\b(?:code|program|script|function|class|application|app|website|webpage|"
    r"bot|automation|api|macro|algorithm)\b", re.I)
SHOW = re.compile(r"show\s+(?:me\s+)?(?:the\s+|all\s+)?(\w+)"
                  r"(?:\s+(?:in|from|inside)\s+(?:my\s+|the\s+)?([\w ]+?)(?:\s+folder)?)?$")
IN_WINDOWS = re.compile(r"(?:search|find)\s+(?:for\s+)?(\S+(?:\s+\S+)*?)\s+(?:in|on)\s+windows$")
NAMED_FOLDER = re.compile(r"(?:open|go to)\s+(?:my\s+|the\s+)?(\w+(?:\s+\w+)*?)\s+folder")
FILE_SEARCH = re.compile(
    r"(?:search|find|look for)\s+(?:my\s+|the\s+)?(?:files?|notes|documents?|laptop|computer|pc)"
    r"\s+(?:for|that (?:has|have|mentions?|contains?|says?|includes?))\s+(.+)")
DIR_NAMED = re.compile(r"(?:open|go to)\s+(?:the\s+)?(?:directory|folder|path)\s+([A-Za-z]:[\\/][^\s]+|~/[^\s]+)")
DIR_PATH = re.compile(r"(?:open|go to)\s+([A-Za-z]:[\\/][^\s]+|~/[^\s]+)$")
DRIVES = re.compile(r"(?:what\s+)?drives?\s+(?:do i have|do you have|are there|list)?")
LIST_DRIVES = re.compile(r"list\s+(?:the\s+)?drives?")
FILE_INFO = re.compile(r"(?:how\s+big\s+is|what\s+size\s+is|when\s+was|where\s+is|info\s+on|"
                       r"size\s+of)\s+(?:the\s+)?(.+)")
MUTE = re.compile(r"(?:mute|unmute)(?:\s+(?:the\s+)?(?:sound|volume|audio))?")
VOLUME = re.compile(r"\bvolume\b|\blouder\b|\bquieter\b|\bsofter\b")
DIGIT = re.compile(r"\d")
WIFI = re.compile(r"(?:turn\s+)?(?:(on|off)\s+)?(?:the\s+)?wi-?fi(?:\s+(on|off))?")
MEDIA = re.compile(r"(?:media\s+)?(pause|resume|next|skip|previous|back|stop)"
                   r"(?:\s+(?:the\s+)?(?:song|track|video|music))?")
CANCEL = re.compile(r"cancel (?:the )?(?:shutdown|restart)|(?:don't|do not) shut ?down")
RECYCLE = re.compile(r"empty (?:the )?(?:recycle bin|trash)")
PING = re.compile(r"ping\s+([\w.:-]+)")
PLAY = re.compile(r"(?:play|put on)\s+(?:the\s+)?(\S+(?:\s+\S+)*?)(?:\s+on\s+youtube)?$")
SEARCH_FOR = re.compile(r"(?:search|google|look up|find)\s+(?:for\s+)?(.+)")
ON_SITE = re.compile(r"\s(?:on|in)\s+(\w+)$")
SETTINGS = re.compile(r"\bsettings?\b|\boptions?\b")
OPEN = re.compile(r"(?:open|launch|start)\s+(?:my\s+|the\s+)?(.+)")
APP_SUFFIX = re.compile(r"\s(?:app|application|file)$")
MEDIA_SAID = {"play_pause": "Toggled playback", "next": "Skipped to the next track",
              "previous": "Went back a track", "stop": "Stopped playback"}
