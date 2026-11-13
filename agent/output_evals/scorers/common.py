"""Shared pieces for the output scorers.

Every scorer answers one question: given the verbatim model output for a
recorded call, does it pass the automatic check for that kind? None of them
judges quality; a judge is a separate, named, optional path (spec: "The judge
is used").

Fail-closed rules, learned the hard way in this rig:
  - an unreadable or empty table of allowed values is an ERROR, never a pass;
    a surface check against an empty set vouches for nothing;
  - a caller that cannot supply the thing being checked gets `unscorable`, not
    `pass`. A missing measurement must not become a good number.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

PASS = "pass"
FAIL = "fail"
UNSCORABLE = "unscorable"


@dataclass
class Result:
    verdict: str
    reason: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict == PASS


def strip_fence(text: str) -> str:
    """Remove a ```json ... ``` fence if the model wrapped its output in one.

    The planner does this before parsing (`l3_planner._extract_json`), so the
    eval must too, or it scores a failure the agent would not have.
    """
    if not isinstance(text, str):
        return ""
    t = text.strip()
    m = re.match(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```\s*$", t, re.S)
    if m:
        return m.group(1).strip()
    return t


def parse_json(text):
    """(value, error). Never raises."""
    body = strip_fence(text)
    if not body:
        return None, "empty output"
    try:
        return json.loads(body), None
    except (ValueError, TypeError) as e:
        return None, f"not JSON: {e}"


def _as_kind_map(allowed):
    """Normalise the allowed-kind argument to a dict name -> allowed params.

    Accepts a mapping (`{kind: [args]}`) or an iterable of names. Anything else,
    including None or an empty collection, is an error: a kind surface that
    cannot be read must not silently permit everything or nothing.
    """
    if isinstance(allowed, dict):
        if not allowed:
            raise ValueError("allowed-kind mapping is empty")
        return {str(k): (set(v) if v is not None else set()) for k, v in allowed.items()}
    if isinstance(allowed, (list, tuple, set, frozenset)):
        names = set(allowed)
        if not names:
            raise ValueError("allowed-kind set is empty")
        return {str(k): set() for k in names}
    raise ValueError(f"allowed kinds unreadable: got {type(allowed).__name__}")


def check_kind_surface(items, allowed, param_key="args"):
    """Check a list of directive dicts against the allowed kind surface.

    Returns a list of problem strings; empty means clean. Each item must be a
    dict with a `kind` that is allowed, and -- when the surface lists params for
    that kind -- no keys outside the allowed set (plus `kind` itself).
    """
    kinds = _as_kind_map(allowed)
    problems = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"item {i} is not an object")
            continue
        kind = item.get("kind")
        if not isinstance(kind, str) or not kind:
            problems.append(f"item {i} has no kind")
            continue
        if kind not in kinds:
            problems.append(f"item {i}: kind {kind!r} not in the allowed surface")
            continue
        permitted = kinds[kind]
        if not permitted:
            # No param list published for this kind: check the name only.
            continue
        extra = set(item) - {"kind"} - permitted
        if extra:
            problems.append(f"item {i}: {kind} has params outside the surface: {sorted(extra)}")
    return problems
