"""Choosing how Wilco sounds — which voice pack it speaks in, and how fast.

Both take effect on the very next thing said, which is the reply to this turn, so the user
hears the change rather than being told about it.
"""
from windows import voice as engine


def list_voices():
    """List every voice Wilco can speak in, with the accent and gender of each, and say which
    one is in use. Call this whenever the user asks what voices there are, or asks for a kind
    of voice rather than a name — a British one, an Indian one, a woman's voice — so that the
    name you then pass to set_voice is one that actually exists."""
    name, _, _, speed = engine.current()
    described = "; ".join(f"{n} — {d}" for n, (_, d) in engine.VOICES.items())
    return (f"Voices: {described}. Right now Wilco is {name}, talking at {speed:+d}% "
            f"of normal speed.")


def set_voice(name):
    """Switch the voice Wilco speaks in. Your reply to this turn is already spoken in the new
    voice, so keep it to a short line like "How's this one?" and let them hear it. name: one
    of ava, andrew, emma, brian, sonia, ryan, neerja, prabhat, natasha, madhur, swara, david,
    zira. david and zira are the built-in Windows voices — offline and instant, but flat."""
    chosen = engine.use(name)
    if not chosen:
        return (f"There's no voice called {name}. The ones there are: "
                f"{', '.join(engine.VOICES)}.")
    return f"Now speaking as {chosen} — {engine.VOICES[chosen][1]}."


def set_speech_speed(percent: int):
    """Set how fast Wilco talks, as a percentage on top of the voice's normal pace: 0 is that
    voice's own speed, 25 is the brisk default, 60 is fast, -20 is slow. This is the one for
    "talk faster", "slow down", "you're speaking too quickly". Range -50 to 100."""
    return f"Talking speed set to {engine.set_speed(percent):+d}% of normal."
