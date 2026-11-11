"""Cheap chat-noise filter, kept dependency-free so it is unit-testable.

A message that is *entirely* a pleasantry ("thanks", "ok", "hey") is noise and
should not provoke a reply or a plan. A message that merely STARTS with one but
carries real content ("Hi Mystic! Who are you?") is a real message and must not
be dropped.

The old rule was a prefix test (`text.lower().startswith("hi ")`), which
silently discarded exactly such messages — with no log line — so a direct
question to a bot got no reply (P4, in-game check 2026-09-30).
"""
from __future__ import annotations

import re

# Single-word pleasantries/acks that carry no instruction.
_SKIP_TOKENS = frozenset({
    "hello", "hi", "hey", "yo", "sup",
    "thanks", "thank", "thx", "ty",
    "yes", "yeah", "yep", "no", "nope",
    "ok", "okay", "k", "kk",
})

_WORD_RE = re.compile(r"[^a-z0-9]+")


def is_pure_pleasantry(text: str, bot_name: str = "") -> bool:
    """True only when the whole message is pleasantries (optionally addressing
    the bot by name and nothing else). Empty/punctuation-only text is noise.

    >>> is_pure_pleasantry("thanks")
    True
    >>> is_pure_pleasantry("Hi Mystic! Who are you?", "Mystic")
    False
    >>> is_pure_pleasantry("hi mystic", "Mystic")
    True
    """
    words = [w for w in _WORD_RE.split(text.lower().strip()) if w]
    if not words:
        return True
    name = bot_name.lower()
    return all(w in _SKIP_TOKENS or w == name for w in words)
