"""Devanagari to Latin letters, done here rather than by asking the model.

Romanising used to cost a whole extra API call on every Hindi reply — a third of the month's
quota for someone who speaks Hindi, spent on a lookup table. The mapping is deterministic, so
it belongs in code: same answer every time, no network, no tokens, no wait.

Hindi drops the inherent 'a' at the end of a word, so म-ै-स-े-ज is maisej and not maiseja.
That one rule is most of the difference between this reading naturally and sounding robotic.
"""

CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "ळ": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}
VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
          "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o"}
MATRAS = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
          "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o"}
SIGNS = {"ं": "n", "ँ": "n", "ः": "h", "़": "", "।": ".", "॥": "."}
DIGITS = {d: str(i) for i, d in enumerate("०१२३४५६७८९")}
VIRAMA = "्"


def _devanagari(ch):
    return "ऀ" <= ch <= "ॿ"


def has_devanagari(text):
    return any(_devanagari(c) for c in text or "")


def romanise(text):
    """Devanagari written in Latin letters, the way people type Hinglish in chat."""
    out, i, size = [], 0, len(text)
    while i < size:
        pair = text[i:i + 2]
        if pair in CONSONANTS:
            sound, i = CONSONANTS[pair], i + 2
        elif text[i] in CONSONANTS:
            sound, i = CONSONANTS[text[i]], i + 1
        else:
            sound = None

        if sound is not None:
            out.append(sound)
            if i < size and text[i] == VIRAMA:
                i += 1
            elif i < size and text[i] in MATRAS:
                matra = MATRAS[text[i]]
                i += 1
                # mid-word the आ-matra is long — kaam, kaart — but at the end of a word
                # Hinglish writes it short: kya, khelega, achha
                if matra == "aa" and (i >= size or not _devanagari(text[i])):
                    matra = "a"
                out.append(matra)
            elif i < size and _devanagari(text[i]):
                out.append("a")
            continue

        ch = text[i]
        for table in (VOWELS, MATRAS, DIGITS, SIGNS):
            if ch in table:
                out.append(table[ch])
                break
        else:
            out.append(ch)
        i += 1
    return "".join(p for p in out if p)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    CASES = [
        ("सचीन को मैसेज करो", "sacheen ko maisej karo"),
        ("दिल्ली", "dillee"),
        ("करो", "karo"),
        ("है", "hai"),
        ("कोई स्मैस कार्ट खेलेगा क्या", "koee smais kaart khelega kya"),
        ("मैं बढ़िया हूँ", "main barhiya hoon"),
        ("Chrome खोलो", "Chrome kholo"),
        ("plain english stays", "plain english stays"),
        ("२०२५", "2025"),
    ]
    for source, want in CASES:
        got = romanise(source)
        print(("ok  " if got == want else "FAIL"), repr(source), "->", repr(got),
              "" if got == want else f"(wanted {want!r})")
