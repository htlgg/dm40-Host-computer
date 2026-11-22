"""Short confirmation sounds for the shortcut toggles.

The tones are synthesised at runtime (a small WAV in memory), so the volume can
be scaled without touching the system mixer and no audio files ship with the app.
"""

from __future__ import annotations

import io
import math
import struct
import sys
import wave

SAMPLE_RATE = 22050

STYLE_SINGLE = "single"
STYLE_DOUBLE = "double"
STYLE_CHIME = "chime"
STYLE_TICK = "tick"
STYLES = (STYLE_SINGLE, STYLE_DOUBLE, STYLE_CHIME, STYLE_TICK)

DEFAULT_STYLE = STYLE_SINGLE
DEFAULT_VOLUME = 60

# (kind, style) → list of (frequency, seconds, gap_after)
_PATTERNS = {
    ("on", STYLE_SINGLE): [(880, 0.10, 0)],
    ("off", STYLE_SINGLE): [(587, 0.10, 0)],
    ("on", STYLE_DOUBLE): [(880, 0.06, 0.03), (1175, 0.08, 0)],
    ("off", STYLE_DOUBLE): [(587, 0.06, 0.03), (440, 0.08, 0)],
    ("on", STYLE_CHIME): [(784, 0.07, 0.02), (988, 0.07, 0.02), (1319, 0.12, 0)],
    ("off", STYLE_CHIME): [(988, 0.07, 0.02), (784, 0.07, 0.02), (523, 0.12, 0)],
    ("on", STYLE_TICK): [(1568, 0.035, 0)],
    ("off", STYLE_TICK): [(1047, 0.035, 0)],
}

_cache: dict[tuple[str, str, int], bytes] = {}


def _samples(freq: float, seconds: float, volume: int) -> bytes:
    count = max(1, int(SAMPLE_RATE * seconds))
    amplitude = 32767 * max(0, min(100, volume)) / 100.0
    attack = max(1, int(SAMPLE_RATE * 0.004))
    release = max(1, int(SAMPLE_RATE * 0.012))
    out = bytearray()
    for index in range(count):
        env = 1.0
        if index < attack:
            env = index / attack
        elif index > count - release:
            env = max(0.0, (count - index) / release)
        value = math.sin(2 * math.pi * freq * index / SAMPLE_RATE)
        out += struct.pack("<h", int(amplitude * env * value))
    return bytes(out)


def _build(kind: str, style: str, volume: int) -> bytes:
    key = (kind, style, volume)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    pattern = _PATTERNS.get((kind, style)) or _PATTERNS[(kind, STYLE_SINGLE)]
    pcm = bytearray()
    for frequency, seconds, gap in pattern:
        pcm += _samples(frequency, seconds, volume)
        if gap:
            pcm += b"\x00\x00" * int(SAMPLE_RATE * gap)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(pcm))
    data = buffer.getvalue()
    _cache[key] = data
    return data


def style_labels() -> dict[str, str]:
    """Translated names for the settings UI."""
    from core.i18n import t

    return {style: t(f"sound.style_{style}") for style in STYLES}


def play(settings: dict, kind: str, *, preview_style: str | None = None) -> None:
    """Play the confirmation tone; silently does nothing when unavailable."""
    if sys.platform != "win32":
        return
    if not settings.get("beep_enabled", True):
        return
    try:
        volume = int(settings.get("beep_volume", DEFAULT_VOLUME))
    except (TypeError, ValueError):
        volume = DEFAULT_VOLUME
    if volume <= 0:
        return
    style = (
        preview_style
        or settings.get(f"beep_style_{kind}")
        or settings.get("beep_style")
        or DEFAULT_STYLE
    )
    if style not in STYLES:
        style = DEFAULT_STYLE
    try:
        import threading
        import winsound

        data = _build(kind, style, max(1, min(100, volume)))

        def _play() -> None:
            try:
                # NOTE: SND_ASYNC cannot be combined with SND_MEMORY on Windows
                # ("Cannot play asynchronously from memory"), so play the buffer
                # synchronously on a throw-away thread.
                winsound.PlaySound(data, winsound.SND_MEMORY)
            except Exception:
                try:
                    winsound.Beep(880 if kind == "on" else 587, 90)
                except Exception:
                    pass

        threading.Thread(target=_play, daemon=True).start()
    except Exception:
        pass
