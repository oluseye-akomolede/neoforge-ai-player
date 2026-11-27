"""Script-mode tick for one bot (M2 task 3.2 wiring).

Sits in front of the planner: if a bot has a script and the runner answers,
the script's actions are what the bot does this tick. Otherwise this returns
`handled=False` and the existing L1/L3 path runs exactly as it did before.

The fallback is the whole design constraint (task 7.2: the existing planner
stays the fallback). Three things must therefore be true, and each has a test:

1. **Any failure falls through.** No script, runner down, runner silent,
   runner returns junk -- all of them return `handled=False`, never an
   exception, never an empty action list that suppresses the planner.
2. **The bound is enforced here.** `script_client.call_runner` owns the 300 ms
   bound; this module never calls the runner without it.
3. **Refused actions are visible.** A script whose actions are all refused
   must not look like a silent success -- the caller can log the refusals.

The script itself is executed by the runner service, not here. This module
feeds it a tick and binds what comes back.
"""
from __future__ import annotations

import base64
import json

import action_binding
import snapshot as snapshot_mod
from script_client import (
    STATE_SCRIPT,
    call_runner,
)


# The tick's detail string for "the script ran but every action was refused at
# binding". Producer and consumer MUST import this rather than repeat the
# literal: the caller in agent.py carves this case out of dry-tick failure so a
# `say`-only script still binds, and a reworded literal on either side would
# kill that carve-out silently, with no error anywhere.
DETAIL_ALL_ACTIONS_REFUSED = "all actions refused"

# A script's report is capped at 2 KiB of JSON (design §3). A proposal, not a
# measurement: it is set against the largest genuinely useful report the trial
# produces, and this constant is the one place to change when it is.
RESULT_CAP_BYTES = 2048

# Marks a result that was cut. The planner MUST be able to tell "the script
# reported this much" from "the script reported exactly this" -- a truncated
# report read as complete is a report that lies about its own extent.
RESULT_TRUNCATED_MARKER = "...[truncated]"

# ── Declared queries (change script-lookups-and-results, owner A2) ──────────
#
# A script declares its searches once, at the top, as a LITERAL:
#
#   queries = [{name: "ore", kind: "blocks", id: "minecraft:diamond_ore", radius: 32}]
#
# and reads the results as look.queries.ore. The agent fetches them before
# the tick, so reading one spends no host call and cannot stall the sandbox
# mid-script. The declaration is read from the SOURCE TEXT and never executed:
# a declaration that is executed to be read would be arbitrary code running
# before the script's budget.

# The most declarations one script may make. Bounds the pre-tick mod work by
# count; the radius clamps below bound it per query.
MAX_DECLARED_QUERIES = 16

# Caller-side clamps. The mod clamps nothing (HttpApiServer.java:1117-1134,
# findBlocks iterates the full cube, BotPlayer.java:1286-1309), so a script
# asking for radius 1000 would be asking the server for one. A value over a
# clamp is NARROWED, and the result records clamped so the script can tell
# its search was smaller than it asked.
MAX_BLOCK_RADIUS = 32
MAX_ENTITY_RADIUS = 32
MAX_RESULTS = 16

# Total pre-tick scan allowed before the agent logs that a tick is over budget.
# 2x one radius-32 cube (the search volume a radius-32 find is proportional
# to). Over budget the queries STILL RUN, with a log line naming the count: a
# hard refusal here would silently break a working script over a number that is
# a proposal until task 7.6 measures the real cost.
QUERY_SCAN_BUDGET = 2 * MAX_BLOCK_RADIUS ** 3

# locate's client-side bound. The other three reads keep api.py's default
# transport timeout: an early tick after a slow read is closer to the tick
# being readable than to the script being starved, and api.* exposes no
# per-call timeout knob for them. locate IS configurable and needs it -- a
# cold structure search through ungenerated chunks is the one read that is
# legitimately slow (api.py:143), and its 120 s default would hold the whole
# pre-tick phase. Locating costs no tick slot once the script has drawn it,
# because a structure does not move.
LOCATE_TIMEOUT = 20.0

# The kinds and the keys each may declare. id is the block/entity/structure
# name for every kind; type is refused rather than aliased, because two names
# for one key is a second thing to keep in step with no gain.
_QUERY_KEYS = {
    "blocks": {"name", "kind", "id", "radius", "max"},
    "entities": {"name", "kind", "id", "radius"},
    "block_at": {"name", "kind", "x", "y", "z"},
    "locate": {"name", "kind", "id"},
}
_REQUIRED_KEYS = {
    "blocks": {"name", "kind", "id"},
    "entities": {"name", "kind", "id"},
    "block_at": {"name", "kind", "x", "y", "z"},
    "locate": {"name", "kind", "id"},
}


class DeclaredQueriesError(ValueError):
    """A script's queries declaration is not an acceptable literal list."""


def parse_declared_queries(source):
    """Return the validated list of declared queries, or [] when absent.

    A strict literal parse of [const|let|var] queries = [<object literals>],
    NOT ast.parse and NOT eval:

      * ast.parse accepts JS by accident -- measured: return 1 parses as
        Python, so a Python parse would accept a declaration that never
        appears in the JavaScript source this runner will execute.
      * eval executes. The whole point of reading the source is that nothing
        in it runs before the tick's budget.

    The two rules that the first prototype lacked, and that made it pass
    attackers (queries = [...literal...] + evil() still executed evil()):

      * the declaration appears AT MOST ONCE -- a second one would diverge from
        the one that was validated;
      * nothing follows the closing ] on the statement but a terminator
        (;, a newline) or a comment.

    Raises DeclaredQueriesError naming the offending declaration. Absent is
    not an error: a script that declares nothing wants nothing fetched.
    """
    found = _find_declaration(source if isinstance(source, str) else "")
    if found is None:
        return []
    start, array_text = found
    items = _split_array_items(array_text, start)
    out = []
    names = set()
    for index, item in enumerate(items):
        query = _parse_query_object(item, index, start)
        if query["name"] in names:
            raise DeclaredQueriesError(
                f"declared query name {query['name']!r} appears twice; "
                f"one result would overwrite the other")
        names.add(query["name"])
        out.append(query)
    if len(out) > MAX_DECLARED_QUERIES:
        raise DeclaredQueriesError(
            f"{len(out)} declared queries; at most {MAX_DECLARED_QUERIES} "
            f"are allowed")
    return out


def _where(source, offset):
    line = source.count("\n", 0, offset) + 1
    return f"line {line}"


def _skip_ws_and_comments(source, i):
    """Advance past whitespace, // and /* */ comments."""
    n = len(source)
    while i < n:
        c = source[i]
        if c in " \t\r\n":
            i += 1
        elif source.startswith("//", i):
            j = source.find("\n", i)
            i = n if j < 0 else j + 1
        elif source.startswith("/*", i):
            j = source.find("*/", i + 2)
            if j < 0:
                raise DeclaredQueriesError(
                    f"{_where(source, i)}: unterminated comment")
            i = j + 2
        else:
            break
    return i


def _mask_comments(text):
    """`text` with every comment BODY blanked to `_`, SAME LENGTH.

    Same contract as `_strip_strings`, and for the same reason: offsets found
    in the mask are reported against the original text, so a mask that shrank
    would shift every later index.

    This exists because a comment is not code. Before it, `_find_declaration`
    scanned the raw source, so a script whose COMMENT mentioned
    `look.queries.<name>` was refused as a property assignment -- the live A2
    E2E failure (2026-11-27): Axiom's line 3 was a comment and the declaration
    it was meant to describe never bound.

    Quotes are left intact, so a `//` inside a string is NOT treated as a
    comment: this pass runs FIRST on the raw source, then `_strip_strings`
    blanks the string bodies. That order is load-bearing and was measured the
    hard way -- stripping strings first let an apostrophe in a COMMENT open a
    string, leaving a lone quote that ran to EOF and swallowed the declaration
    (1 and 3 apostrophes dropped it; 2 and 4 survived by accident).
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            # A string literal: copy it through untouched. `_strip_strings`
            # normally ran first and blanked the body, but this pass must be
            # safe on its own, so it tracks quotes rather than assuming.
            quote = c
            out.append(c)
            i += 1
            while i < n:
                if text[i] == "\\":
                    out.append(text[i:i + 2])
                    i += 2
                    continue
                out.append(text[i])
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append("__" + "_" * (j - i - 2))
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                # Unterminated: blank to the end. `_skip_ws_and_comments`
                # raises for this, so it is not silently swallowed -- this
                # pass only has to not mistake the body for code.
                j = n - 2
            out.append("__" + "_" * (j - i - 2) + "__")
            i = j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_declaration(source):
    """Return `(offset_of_[, text_of_[...])` for the one declaration, or None.

    A declaration is `queries` at an identifier boundary (not a property
    `x.queries = ...`, not `myqueries`) followed by `=`, and followed by `[`.

    SCANNING IS DONE ON CODE, NOT RAW TEXT. Comments and string bodies are
    masked to `_` first (`_mask_comments`, `_strip_strings`, both
    same-length), so neither can be read as a declaration or as a property.
    A property READ (`look.queries.ore`) is legal and is not the declaration:
    only a property ASSIGNMENT (`api.queries = [...]`) is refused, because only
    an assignment could diverge from the declaration the agent validated.
    """
    # Mask, then scan the mask, but take the array text from the ORIGINAL
    # source -- the mask has string bodies blanked and cannot be parsed.
    #
    # ORDER MATTERS: comments are masked on the RAW source first. Stripping
    # strings first lets an apostrophe inside a COMMENT open a string (a
    # comment is free prose -- "the bot's name"), which leaves a lone quote
    # that then runs to EOF and swallows everything after it, including the
    # declaration. Measured before the swap: a 1/3-apostrophe comment before
    # the declaration dropped it (queries 0), 2/4 survived by accident. With
    # comments masked first, a string's `//` and an apostrophe still parse,
    # because the comment mask respects strings while the string mask no
    # longer sees prose.
    masked = _strip_strings(_mask_comments(source))
    hits = []
    n = len(source)
    i = 0
    while True:
        j = masked.find("queries", i)
        if j < 0:
            break
        i = j + len("queries")
        before = masked[j - 1] if j > 0 else ""
        after = masked[i] if i < n else ""
        # `before` must be a non-identifier character or a dot. Written with
        # `isidentifier` rather than a hand-rolled class: "a" + "queries" is
        # `aqueries`, not a declaration, and `_queries`/`$queries` are
        # different names -- but whatever is accepted on the right must NOT be
        # accepted here, or the declaration is never seen (measured: the
        # hand-rolled set was checked with `isalnum` and missed a plain space).
        if before and (before + "queries").isidentifier():
            continue
        if after.isalnum() or after in "_$":
            continue
        if before == ".":
            # Property access. A READ (`look.queries.ore`) is what a script is
            # meant to do and is legal; only an ASSIGNMENT diverges from the
            # validated declaration. Decide by what follows `queries`: skip
            # space and comments, and refuse only on a lone `=`.
            k = _skip_ws_and_comments(masked, i)
            assigned = (k < n and masked[k] == "="
                        and not (k + 1 < n and masked[k + 1] == "="))
            # Compound assignment to a property is also an assignment:
            # `api.queries += [...]`, `||=`, `??=`. The validated literal still
            # governs the first declaration, but refusing these is the same
            # rule -- only an assignment can diverge. Read the whole operator
            # run: `||=` and `??=` are TWO characters before the `=`, so testing
            # only masked[k+1] == "=" misses them (measured: they were ACCEPTed).
            if not assigned and k < n:
                run = k
                while run < n and masked[run] in "+-*/%&|^?<>":
                    run += 1
                # A pure operator run ending in `=` is an assignment; `==` and
                # `===` are compares (their run never contains a non-`=` before
                # the `=` at the position tested, so they fall through).
                if run > k and run < n and masked[run] == "=" and \
                        not (run + 1 < n and masked[run + 1] == "="):
                    assigned = True
            if assigned:
                raise DeclaredQueriesError(
                    f"{_where(source, j)}: `queries` must be a bare assignment, "
                    f"not a property")
            continue
        k = _skip_ws_and_comments(masked, i)
        if k >= n or masked[k] != "=" or (k + 1 < n and masked[k + 1] == "="):
            continue
        k = _skip_ws_and_comments(masked, k + 1)
        if k >= n or masked[k] != "[":
            raise DeclaredQueriesError(
                f"{_where(source, j)}: `queries` must be assigned an array "
                f"literal; anything dynamic is refused, not executed")
        hits.append((j, k))
        if len(hits) > 1:
            raise DeclaredQueriesError(
                f"{_where(source, hits[1][0])}: `queries` is declared more "
                f"than once; a second declaration would diverge from the one "
                f"that was validated")
    if not hits:
        return None
    j, k = hits[0]
    # Find the matching `]`, string-aware.
    depth = 0
    m = k
    in_str = None
    while m < n:
        c = source[m]
        if in_str:
            if c == "\\":
                m += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "\"'`":
            in_str = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                break
        m += 1
    if m >= n:
        raise DeclaredQueriesError(
            f"{_where(source, j)}: the `queries` array is not closed")
    # Tail rule: after the closing `]` only a terminator (or a comment) may
    # follow, and the statement must END there. A `;` starts a NEW statement,
    # so what comes after it is script code that was never validated --
    # measured (review F-1): the old rule accepted `queries = [...]; evil()`
    # while `+ evil()` was refused, which is the exact false assurance this
    # rule exists to prevent. So after a `;` or a newline, skip trivia and
    # require end-of-source: a `;` followed by more code on its own line is
    # refused, and so is a newline followed by more code.
    # On the terminator's line only a `;` and comments may follow the `]`;
    # anything else is unvalidated script code. The first line break ends the
    # statement, and whatever comes after it is ordinary script.
    #
    # Measured (review: F-1, then the no-semicolon residual): the earlier
    # form skipped trivia BEFORE deciding, which ate the newline, so a bare
    # `] // why` or `]` followed by code was refused while the `];` forms were
    # accepted -- the rule and the spec disagreed on a case no test covered.
    # One loop now handles both: the `;` is optional, and only a non-trivia
    # character on the terminator's line is a refusal.
    after = m + 1
    while after < n:
        c = source[after]
        if c == "\n":
            break
        if c in " \t\r;":
            after += 1
        elif source.startswith("//", after):
            j = source.find("\n", after)
            after = n if j < 0 else j   # stop BEFORE the newline
        elif source.startswith("/*", after):
            j = source.find("*/", after + 2)
            if j < 0:
                raise DeclaredQueriesError(
                    f"{_where(source, after)}: unterminated comment")
            if "\n" in source[after:j]:
                # Measured: letting a multi-line block comment end the rule
                # accepted `]; /* a\n */ evil()`, and evil() runs. A comment
                # may not carry the statement across a line, so this is
                # refused rather than treated as a line break.
                raise DeclaredQueriesError(
                    f"{_where(source, after)}: a comment after the closing `]` "
                    f"of `queries` must stay on its line")
            after = j + 2
        else:
            raise DeclaredQueriesError(
                f"{_where(source, after)}: nothing may follow the closing "
                f"`]` of `queries` on its statement but a terminator or "
                f"comment -- put script code on a new line")
    return k, source[k + 1:m]


def _strip_strings(text):
    """`text` with the BODY of every string literal blanked to `_`.

    SAME LENGTH as the input, always: every offset found in the mask is
    reported against the original text, and a mask that shrank (`""` for a
    20-character id) shifted every later index -- measured: it split
    `{name: 'c', kind: 'blocks', ...}` after the first string, so a valid
    declaration read as a list of nothing.

    Blanking keeps quotes (so the mask still shows a literal was there) but
    makes a comma or bracket inside one unable to be read as structure.
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            quote = c
            out.append(quote)
            i += 1
            while i < n:
                if text[i] == "\\":
                    out.append("__")
                    i += 2
                    continue
                if text[i] == quote:
                    out.append(quote)
                    i += 1
                    break
                out.append("_")
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _split_array_items(text, offset):
    """Split the array body into object-literal texts, or refuse.

    Accepts ONLY a comma-separated list of `{...}` literals (trailing comma
    allowed). A spread, a call, an identifier or a nested array is refused
    here rather than later, because the error names the position.
    """
    mask = _strip_strings(text)
    items = []
    depth = 0
    start = None
    for idx, c in enumerate(mask):
        if c == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                raise DeclaredQueriesError(
                    f"{_where(text, idx)}: unbalanced `}}` in `queries`")
            if depth == 0:
                items.append(text[start:idx + 1])
                start = None
        elif depth == 0 and c not in " \t\r\n,":
            raise DeclaredQueriesError(
                f"`queries` at {_where(text, idx)}: only object literals are "
                f"allowed; {c!r} is not")
    if depth != 0:
        raise DeclaredQueriesError("`queries`: an object literal is not closed")
    if not text.strip():
        return []
    return items



def _parse_scalar(text):
    """One literal value: a string, a number, true/false/null. Refuse the rest."""
    import re
    t = text.strip()
    if not t:
        raise DeclaredQueriesError("empty value in a declared query")
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        try:
            return json.loads('"' + t[1:-1].replace('\\\'', "'")
                              .replace('"', '\\"') + '"')
        except ValueError:
            raise DeclaredQueriesError(f"unreadable string literal {t!r}")
    if t in ("true", "false"):
        return t == "true"
    if t == "null":
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", t):
        return float(t) if "." in t else int(t)
    raise DeclaredQueriesError(
        f"a declared query's value must be a string, number, true, false or "
        f"null; got {t!r}")


def _parse_query_object(item, index, base_offset):
    """Validate one `{...}` literal and return the query dict."""
    inner = item.strip()
    if not (inner.startswith("{") and inner.endswith("}")):
        raise DeclaredQueriesError(f"declared query #{index + 1} is not an object")
    pairs = _split_object_pairs(inner[1:-1])
    obj = {}
    for key, value in pairs:
        k = _parse_key(key)
        # An unknown key (including __proto__, which a JSON parse would let
        # through as an own property) is refused by this allow-list, not by
        # trusting the parser.
        if k == "__proto__":
            raise DeclaredQueriesError("`__proto__` is not an allowed query key")
        if k in obj:
            raise DeclaredQueriesError(f"declared query #{index + 1} repeats key {k!r}")
        obj[k] = _parse_scalar(value)
    kind = obj.get("kind")
    if kind not in _QUERY_KEYS:
        raise DeclaredQueriesError(
            f"declared query #{index + 1}: unknown kind {kind!r}; expected one "
            f"of {sorted(_QUERY_KEYS)}")
    unknown = set(obj) - _QUERY_KEYS[kind]
    if unknown:
        raise DeclaredQueriesError(
            f"declared query #{index + 1} (kind {kind!r}) has key(s) "
            f"{sorted(unknown)} it does not take")
    missing = _REQUIRED_KEYS[kind] - set(obj)
    if missing:
        raise DeclaredQueriesError(
            f"declared query #{index + 1} (kind {kind!r}) needs {sorted(missing)}")
    name = obj["name"]
    if not isinstance(name, str) or not name.isidentifier():
        raise DeclaredQueriesError(
            f"declared query #{index + 1}: name {name!r} must be a plain "
            f"identifier, because it is read as `look.queries.<name>`")
    if kind in ("blocks", "entities", "locate"):
        if not isinstance(obj["id"], str) or not obj["id"]:
            raise DeclaredQueriesError(
                f"declared query {name!r}: id must be a non-empty string")
    if kind == "block_at":
        for axis in ("x", "y", "z"):
            if not isinstance(obj[axis], int) or isinstance(obj[axis], bool):
                raise DeclaredQueriesError(
                    f"declared query {name!r}: {axis} must be an integer")
    for numeric in ("radius", "max"):
        if numeric in obj and (not isinstance(obj[numeric], int)
                               or isinstance(obj[numeric], bool)):
            raise DeclaredQueriesError(
                f"declared query {name!r}: {numeric} must be an integer")
    return obj


def _parse_key(text):
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    if t.isidentifier():
        return t
    raise DeclaredQueriesError(f"unreadable key {t!r} in a declared query")


def _split_object_pairs(body):
    """Split `k: v, k: v` at top-level commas, respecting strings and nesting."""
    mask = _strip_strings(body)
    pairs = []
    depth = 0
    start = 0
    for idx, c in enumerate(mask):
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        elif c == "," and depth == 0:
            pairs.append(body[start:idx])
            start = idx + 1
    pairs.append(body[start:])
    out = []
    for pair in pairs:
        if not pair.strip():
            continue
        m = _strip_strings(pair)
        colon = m.find(":")
        if colon < 0:
            raise DeclaredQueriesError(f"declared query entry {pair.strip()!r} has no `:`")
        out.append((pair[:colon], pair[colon + 1:]))
    return out


def _refused(reason, message):
    return {"ok": False, "reason": reason, "message": message}


def plan_declared_queries(queries):
    """The mod calls for a validated list: one per distinct `(kind, id)`.

    Duplicates collapse because two names for one search are ONE search: the
    second would cost the same pre-tick scan for the same answer. `block_at`
    collapses on its coordinates instead (its "id" is a position).
    """
    calls = []
    by_key = {}
    for query in queries:
        kind = query["kind"]
        if kind in ("blocks", "entities", "locate"):
            key = (kind, query["id"])
        else:
            key = (kind, query["x"], query["y"], query["z"])
        if key not in by_key:
            by_key[key] = _plan_call(query)
            calls.append(key)
    return [by_key[k] for k in calls]


def _plan_call(query):
    """`(key, call, clamped)` for one query, clamps applied caller-side."""
    kind = query["kind"]
    clamped = {}
    if kind == "blocks":
        radius = int(query.get("radius", MAX_BLOCK_RADIUS))
        if radius > MAX_BLOCK_RADIUS:
            clamped["radius"] = MAX_BLOCK_RADIUS
        max_count = int(query.get("max", 10))
        if max_count > MAX_RESULTS:
            clamped["max"] = MAX_RESULTS
        return kind, dict(id=query["id"], radius=min(radius, MAX_BLOCK_RADIUS),
                          max=min(max_count, MAX_RESULTS)), clamped
    if kind == "entities":
        radius = int(query.get("radius", MAX_ENTITY_RADIUS))
        if radius > MAX_ENTITY_RADIUS:
            clamped["radius"] = MAX_ENTITY_RADIUS
        return kind, dict(id=query["id"], radius=min(radius, MAX_ENTITY_RADIUS)), clamped
    if kind == "block_at":
        return kind, dict(x=query["x"], y=query["y"], z=query["z"]), clamped
    return kind, dict(id=query["id"]), clamped


def run_declared_queries(api, bot, queries):
    """Run the declared queries through the four read routes. Returns a map.

    Reads only `api.find_blocks`, `api.find_entities`, `api.block_at` and
    `api.locate`. One call per distinct query; every declared name then reads
    that call's result. A failing or timed-out call is that name's
    `{ok: false, reason, message}` and nothing else: it does not raise, does
    not drop siblings and does not fail the tick.

    Returns `None` when nothing is declared, so the envelope carries no
    `queries` key at all and a script without declarations sends the same bytes
    it always did.
    """
    import requests
    if not queries:
        return None
    planned = plan_declared_queries(queries)
    results = []
    scan = 0
    for kind, params, clamped in planned:
        if kind in ("blocks", "entities"):
            scan += (2 * params["radius"] + 1) ** 3
        try:
            if kind == "blocks":
                value = api.find_blocks(bot, params["id"],
                                        params["radius"], params["max"])
            elif kind == "entities":
                value = api.find_entities(bot, params["id"],
                                          float(params["radius"]))
            elif kind == "block_at":
                value = api.block_at(bot, params["x"], params["y"], params["z"])
            else:
                value = api.locate(bot, params["id"], timeout=LOCATE_TIMEOUT)
        except requests.exceptions.Timeout:
            value = _refused("timeout", f"{kind} did not answer within its bound")
        except requests.exceptions.RequestException as e:
            value = _refused("unavailable", f"{kind} could not be read: "
                                            f"{type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001 - a bad answer is one query's problem
            value = _refused("error", f"{kind} failed: {type(e).__name__}: {e}")
        else:
            if isinstance(value, dict):
                value = dict(value)
                value.setdefault("ok", True)
                value.setdefault("kind", kind)
            else:
                value = _refused("error", f"{kind} returned a non-object answer")
            if clamped:
                value["clamped"] = dict(clamped)
        results.append((kind, params, value))
    if scan > QUERY_SCAN_BUDGET:
        print(f"[queries] budget exceeded: declared searches scan {scan} cells, "
              f"budget {QUERY_SCAN_BUDGET}")
    by_key = {}
    for kind, params, value in results:
        if kind in ("blocks", "entities", "locate"):
            key = (kind, params["id"])
        else:
            key = (kind, params["x"], params["y"], params["z"])
        by_key[key] = value
    out = {}
    for query in queries:
        kind = query["kind"]
        if kind in ("blocks", "entities", "locate"):
            out[query["name"]] = by_key[(kind, query["id"])]
        else:
            out[query["name"]] = by_key[(kind, query["x"], query["y"], query["z"])]
    return out


def cap_result(value=None, *, text=None):
    """Return `(text, truncated)` -- the script's report as capped JSON text.

    A truncated result is KEPT, not dropped: a partial report the planner can
    see beats a missing one. The cap is applied to the serialised text, so it
    is about what the planner actually receives, not about the object's shape.

    Two things this deliberately does NOT do:

    - It does not deepen the cap by dropping keys. Re-serialising "everything
      except the big field" would need a rule for which field is expendable,
      and there is none -- the script decides what is worth reporting.
    - It does not truncate mid-escape and leave invalid JSON. The cut lands on
      the serialised text and the marker is appended, so the consumer is
      always reading a string it can quote, never a broken document it must
      repair.

    Pass `text=` instead of `value()` to cap a string that is ALREADY JSON --
    the runner serialises the script's report before it crosses the wire, so
    the agent holds text, not an object. Passing that text as `value` would
    serialise it a second time and turn `{"a":1}` into `"{\\"a\\":1}"`.

    Returns `(None, False)` for a value that is not reportable at all, so the
    caller can treat "no report" as its own case rather than as an empty one.
    """
    if text is None:
        if value is None:
            return None, False
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            # Not serialisable. Reported as absent rather than as a repr: a repr
            # of an unserialisable object is not what the script meant.
            return None, False
    raw = text.encode("utf-8")
    if len(raw) <= RESULT_CAP_BYTES:
        return text, False
    # The cap bounds what the PLANNER RECEIVES, marker included -- so the body
    # is cut to leave room for the marker rather than cutting to the full limit
    # and appending the marker on top of it. Cutting to RESULT_CAP_BYTES and
    # then appending returned 2062 bytes for a 2048-byte cap; nothing caught it
    # because the older tests asserted the marker and the prefix but never the
    # total length.
    room = RESULT_CAP_BYTES - len(RESULT_TRUNCATED_MARKER.encode("utf-8"))
    # errors="ignore" drops the partial character the byte cut lands on, so the
    # text stays valid UTF-8. Measured against a hand walk that backs up to the
    # boundary character by character: the two agree on every input tried
    # (2046-2048 bytes over six paddings), because both yield the longest valid
    # prefix. Simpler and the same, so this is the one that ships.
    return raw[:room].decode("utf-8", "ignore") + RESULT_TRUNCATED_MARKER, True


def result_verdict(text):
    """Whether the script's reported result says the work SUCCEEDED.

    The trigger the planner sees used to be hard-coded `"done"` whatever the
    script reported, so a script that returned `"Failed: no diamond_ore found"`
    closed its goal as DONE and the goal then never re-planned. The classifier
    is the script's OWN structured flag -- the `done` field the prompt and the
    spec already show (`api.result({done: true, ...})`) -- NOT its prose: a
    script reporting `{done: false}` must not have to avoid the word "failed"
    in a message, and a successful result is free to contain it.

    Returns True (the goal is met), False (the script reports it is still
    WORKING -- e.g. `{done: false, reason: "waiting for night"}`), or None (no
    verdict: not a JSON object, or no boolean `done`). None is NOT success --
    callers must treat "the script did not say" as distinct from "the script
    said done", so a plain-text result keeps whatever handling it had before.

    `False` is NOT a failure. It answers "is the goal met", not "did this tick
    throw"; a waiting script returns it every tick until its condition arrives.
    A real failure is a throw or a non-ok runner status, which this function
    cannot see -- that is carried separately as `result["error"]`. Conflating
    the two unbound a working script on its first tick (TEST 2026-11-22 12:28Z:
    Mystic's `{done:false,"reason":"waiting for night"}` was delivered as
    "Script result (error)" and the goal was lost).
    """
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or "done" not in parsed:
        return None
    done = parsed["done"]
    if not isinstance(done, bool):
        return None
    return done


def no_runner_detail():
    """One wording, used by both the constructor check and the tick."""
    return "no SCRIPT_RUNNER_URL configured"


def no_token_detail():
    """One wording, used by the constructor check and by the tick."""
    return ("no runner token configured (RUNNER_TOKEN unset); "
            "the runner answers 401 to every request without one")


def runner_token():
    """The bearer token the runner requires, or "" when unset.

    The runner enforces this on every contract call
    (agent-script-runner src/server.js): no `Authorization` header is a 401
    before the body is read, so a tick without it cannot succeed. Kept as its
    own function so a test can drive both branches without touching the
    environment of a live pod.
    """
    from config import RUNNER_TOKEN
    return (RUNNER_TOKEN or "").strip()


class RefusedRecord(Exception):
    """A runner action record that cannot be translated into a directive.

    Carries `seq` so a refusal can be matched to the script's own call, which
    is the only handle the script author has on which line was rejected.
    """

    def __init__(self, reason, seq=None):
        super().__init__(reason)
        self.reason = reason
        self.seq = seq


def translate_runner_actions(records):
    """Map the runner's action records onto action_binding's input shape.

    Two shapes exist for the same thing, and this is the single place they
    meet. The runner emits `{seq, call, directive, args}` (agent-script-runner
    src/binding.js) and cardgame consumes that same record, so it is the shared
    contract; `bind_action` owns its own internal shape and its own argument
    allow-list. Teaching the binder to read `directive` is not enough and not
    right: `bind_action` walks every key and refuses any outside
    `_ALLOWED_ARGS`, so `seq`, `call` and `args` would each be refused on their
    own account. The record has to be translated, not widened.

    Returns `(pairs, refusals, deliveries)` where each pair is `(bindable, seq)`
    and each delivery is the runner's raw `say`/`send` record (see
    `validated_deliveries`, which turns it into something a caller can send).
    The seq is
    kept BESIDE the translated record rather than inside it: `bind_action`
    refuses any key outside its argument allow-list, so a `seq` in the dict
    would be refused, and even if admitted it would be stripped by
    `_l3_orchestrator_dispatch`'s signature filter before reaching the mod.
    The seq exists for the log, so it rides alongside -- and pairing here rather
    than in a parallel list means a later refusal cannot slide the indices out
    of step with the actions they describe.

    Refusals are collected rather than raised, matching `bind_actions`, so one
    bad record does not suppress the others. Each refusal carries `seq` and a
    reason.

    `seq` IS NOT AN INDEX, and nothing here may treat it as one. The runner
    resets it to 0 at the start of each tick and increments it on every
    *accepted host call* (`agent-script-runner/src/binding.js:116`), so a
    `say` or `send` between two `do`s consumes a number. A tick can therefore
    emit seqs `{1, 3}` or `{11, 12, 13}`, and the record at position 0 may
    carry seq 3. That is why this function returns `(bindable, seq)` pairs
    rather than zipping a list of seqs against a list of bindables: the two
    lists are different lengths and different sorts of thing, and aligning
    them by position would attach the wrong number to the wrong directive
    exactly when a call was skipped. `seq` is a label for the log line, useful
    precisely because a gap in it says a call happened that produced no
    directive.
    """
    if not isinstance(records, list):
        return [], [{"seq": None,
                     "error": f"actions must be a list, got {type(records).__name__}"}], []

    pairs, refusals, deliveries = [], [], []
    for record in records:
        call = record.get("call") if isinstance(record, dict) else None
        if call in ("say", "send"):
            # Routed OUT of binding, not through it. A say is a chat call and a
            # send is an inter-bot message (M2-PLAN.md:276-280); neither is a
            # DirectiveType, so neither has a `kind` for bind_action to read.
            # Collected in script order so the caller delivers them in the
            # order the script called them.
            deliveries.append(record)
            continue
        try:
            pairs.append(_translate_one(record))
        except RefusedRecord as e:
            refusals.append({"seq": e.seq, "error": e.reason})
    return pairs, refusals, deliveries


def _translate_one(record):
    """One record -> `(bindable, seq)`, or `RefusedRecord`.

    Anything ambiguous is refused, not guessed.
    """
    if not isinstance(record, dict):
        raise RefusedRecord(
            f"action record must be an object, got {type(record).__name__}")

    seq = record.get("seq")
    call = record.get("call")
    if call != "do":
        # `say` and `send` are DELIVERED, not refused, but they are not
        # bindable: they become chat calls and inter-bot messages, never a
        # directive. `translate_runner_actions` routes them out before calling
        # this, so reaching here means an unknown call kind -- refused, with
        # the kind named so the reader can tell a typo from a new action.
        raise RefusedRecord(
            f"unknown action call {call!r}: only 'do' binds to a directive "
            f"(say and send are delivered separately)", seq)

    directive = record.get("directive")
    if not isinstance(directive, str) or not directive.strip():
        raise RefusedRecord(
            f"'directive' must be a non-empty string, got {directive!r}", seq)

    args = record.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise RefusedRecord(
            f"'args' must be an object, got {type(args).__name__}", seq)

    for reserved in ("kind", "action"):
        if reserved in args:
            # `bind_action` reads kind/action as the action name, so an arg by
            # that name would silently become the directive and the real one
            # would be lost.
            raise RefusedRecord(
                f"args may not carry {reserved!r}: it would be read as the "
                f"action name and the directive {directive!r} would be lost", seq)

    return {"kind": directive, **args}, seq


def validated_deliveries(deliveries):
    """Turn runner `say`/`send` records into `(deliverables, refusals)`.

    The shapes are the runner's own (agent-script-runner src/binding.js:259 and
    :271), read from the code that builds them rather than guessed:

        say  -> {seq, call: "say",  text}
        send -> {seq, call: "send", to, msg}

    Validation is repeated here even though the runner already checked these
    types (`api.say` rejects a non-string at :254, `api.send` a non-string or
    empty `otherBot` at :263). The runner version that answers may not be the
    one this agent was written against, and a malformed record must be a named
    refusal rather than a TypeError inside the caller's dispatch loop.

    `send`'s `msg` may be any JSON value (the contract carries it verbatim),
    so it is stringified for the chat path; a `to` that is not a bot id this
    agent knows is the caller's problem, not a shape error, and is passed
    through intact.

    Returns `(deliverables, refusals)`. A deliverable is
    `{"call": "say", "text": str, "seq": seq}` or
    `{"call": "send", "to": str, "text": str, "seq": seq}`.
    """
    out, refused = [], []
    for record in deliveries:
        seq = record.get("seq")
        call = record.get("call")
        if call == "say":
            text = record.get("text")
            if not isinstance(text, str):
                refused.append({"seq": seq,
                                "error": f"say 'text' must be a string, "
                                         f"got {type(text).__name__}"})
                continue
            out.append({"call": "say", "text": text, "seq": seq})
        elif call == "send":
            to = record.get("to")
            if not isinstance(to, str) or not to:
                refused.append({"seq": seq,
                                "error": "send 'to' must be a non-empty bot "
                                         "id string"})
                continue
            msg = record.get("msg")
            out.append({"call": "send", "to": to,
                        "text": "" if msg is None else _stringify_msg(msg),
                        "seq": seq})
        else:
            refused.append({"seq": seq, "error": f"unknown delivery {call!r}"})
    return out, refused


def _stringify_msg(msg):
    """The chat-path text for a `send` payload the contract allows as any JSON."""
    if isinstance(msg, str):
        return msg
    import json
    try:
        return json.dumps(msg, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(msg)


def _number_bind_refusals(translate_refusals, bind_refusals, pairs):
    """Attach the runner's seq to each binder refusal and merge both lists.

    `bind_actions` indexes refusals by position in the list it was given, which
    is a position in `pairs` because that is what it was handed. Mapping back
    through `pairs` is what lets a bind refusal name the script's own call
    instead of an index the script author never sees.
    """
    seqs = [seq for _, seq in pairs]
    merged = list(translate_refusals)
    for refusal in bind_refusals:
        out = dict(refusal)
        idx = out.pop("index", None)
        out["seq"] = seqs[idx] if isinstance(idx, int) and 0 <= idx < len(seqs) else None
        merged.append(out)
    return merged


def _default_transport():
    """A `_post(path, data, timeout=...)` bound to SCRIPT_RUNNER_URL, or None.

    Returns None when the URL is unset so the caller falls through to the
    planner. That is the safe default: a pod with no runner must not POST
    anywhere, and in particular must not POST to the mod.

    The token is read here, not passed in: one place decides how a script tick
    authenticates, and `call_runner` stays transport-agnostic. A missing token
    also returns None for the same reason a missing URL does -- a runner that
    would refuse every call is not a runner, and pretending otherwise turns
    "misconfigured" into "script silently never fires".
    """
    from config import SCRIPT_RUNNER_URL
    base = (SCRIPT_RUNNER_URL or "").strip().rstrip("/")
    token = runner_token()
    if not base or not token:
        return None

    import requests

    def _post(path, data=None, timeout=5):
        r = requests.post(f"{base}{path}", json=data or {}, timeout=timeout,
                          headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return r.json()

    return _post


def _encode_memory(memory):
    """Put a script-memory blob into the wire form the runner expects.

    The runner base64-decodes `memory` on arrival (engine.js:1059,
    `decodeMemory`) and base64-encodes `memory_out` on the way back, so the
    blob travels encoded in both directions. Callers pass the plain str the
    script remembered; the value taken from `memory_out` is already encoded and
    is stored as-is rather than sent through here again, which is why `tick()`
    assigns `result.memory` directly.
    """
    if memory is None:
        return None
    if isinstance(memory, bytes):
        memory = memory.decode("utf-8")
    if isinstance(memory, str):
        return base64.b64encode(memory.encode("utf-8")).decode("ascii")
    raise TypeError("script memory must be str, bytes or None, got %r"
                    % type(memory).__name__)


def _revision_of(source):
    """Stable revision id for a script body.

    The runner keys its source cache on this (§2.1), so two different scripts
    must never collide and the same script must always agree.
    """
    import hashlib
    return hashlib.sha256((source or "").encode("utf-8")).hexdigest()[:16]


class ScriptTick:
    """One bot's script-mode tick.

    `script_source` is the script text. It is sent with every tick because the
    runner is stateless between calls -- the contract has no session handle, and
    inventing one here would be a second protocol to keep in step.

    `api` is the bot's api object; `post` is the runner transport, injected so
    tests do not need a live runner.
    """

    def __init__(self, api, bot, script_source, *, post=None, cache=None,
                 game_id="minecraft", revision=None, memory=None, dry=False):
        self._api = api
        self._bot = bot
        self._source = script_source
        self._game_id = game_id
        # M3-2 step (a): a dry tick asks the runner to evaluate against a
        # throwaway botState, so it neither reads nor spends the bot's live
        # rate windows. The agent cannot do this locally -- botState lives in
        # the runner process, one long-lived object per cached worker -- so
        # this flag on the request body IS the mechanism.
        #
        # False by default, and the field is omitted from the body entirely
        # when false: the runner tests `body.dry === true`, and every existing
        # caller must keep byte-identical behaviour (cardgame shares it).
        self._dry = dry
        # The runner caches source by revision, so the revision must change
        # whenever the script does or a stale script keeps running. Derived
        # from the source by default rather than left to the caller.
        self._revision = revision if revision is not None else _revision_of(script_source)
        self._memory = _encode_memory(memory)
        # The per-bot snapshot cache is shared across ticks so the four-call
        # refresh is paid once per tick rather than once per evaluation.
        self._cache = cache
        self._post = post
        self.renderer = None
        # The script's own log lines from the last tick, and how many the
        # runner's cap dropped. Attributes rather than extra tuple elements:
        # `tick()` returns `(handled, actions, refusals, detail)` and widening
        # that would change every caller for data only the logging path wants.
        # Read after `tick()`; reset at the start of each tick so a caller
        # cannot re-print a previous tick's lines as if they were new.
        self.last_logs = []
        self.last_logs_dropped = 0
        # The `say`/`send` calls this tick delivered, for the caller to send.
        # An attribute for the same reason as last_logs: widening the tick()
        # tuple would touch every caller for data the logging path alone wants.
        self.last_deliveries = []
        # What the script reported via `api.result(v)` this tick, already JSON
        # text and already capped by the runner. None when it reported nothing.
        # An attribute for the same reason as the two above.
        self.last_result = None
        # The runner state this tick ended in, from the same four-value
        # vocabulary the dashboard already uses (STATE_SCRIPT or one of the
        # STATE_FALLBACK_*). None until the first tick has run. Read by the
        # report channel (task 5.6) so the mod is told the state of the tick
        # that was actually sent, not a state the agent inferred afterwards.
        self.last_state = None
        # The declared-query list, read from the source ONCE here rather than
        # per tick: the source only changes with a new object (the runner
        # keys on `_revision`), and a parse failure is a property of the
        # script, not of a tick. Parsed, never executed -- see
        # `parse_declared_queries`. Raises `DeclaredQueriesError`, which the
        # caller surfaces as the script being unrunnable.
        #
        # NOT the same as an engine syntax error, and worth stating because the
        # two differ: an UNTERMINATED string literal is not detected here.
        # `_strip_strings` treats the rest of the file as string body and blanks
        # it to EOF, so a declaration after it is silently lost and `queries`
        # reads `[]`. (Measured: `_mask_comments` leaves such a file untouched;
        # it is the string pass that eats it.) That is safe only because
        # invalid JS cannot reach a tick -- the engine rejects it first. Do not
        # rely on this stage to catch malformed source; it catches schema
        # violations.
        self.queries = parse_declared_queries(script_source)

    @property
    def enabled(self):
        return bool(self._source)

    def tick(self):
        """Return `(handled, actions, refusals, detail)`.

        `handled=False` means "the planner should run this tick" -- the caller
        must never treat it as "do nothing".
        """
        # Cleared first: every early return below leaves the caller reading
        # these, and a previous tick's lines must never be reported as this
        # tick's. A stale log line is worse than a missing one -- it says
        # something happened that did not.
        self.last_logs = []
        self.last_logs_dropped = 0
        self.last_deliveries = []
        self.last_result = None
        self.last_task = None
        # Cleared with the rest: a tick that dies before reaching the runner
        # must not report the previous tick's state as this one's.
        self.last_state = None

        if not self._source:
            return False, [], [], "no script"

        envelope, snap_errors = self._build_snapshot()
        # The declared searches, fetched AFTER the snapshot: `locate` has its
        # own (bounded) timeout and none of the four reads is needed to build
        # the snapshot itself. A read that fails becomes that NAME's
        # `{ok:false,...}` and never changes `handled` -- a script whose search
        # failed still runs, and decides with `look.queries.<name>.ok`.
        if envelope is not None:
            envelope = dict(envelope)
            envelope["queries"] = run_declared_queries(
                self._api, self._bot, self.queries)
            if envelope["queries"] is None:
                # Nothing declared: omit the key so the body stays
                # byte-identical to what every existing caller sends.
                envelope.pop("queries")
        # The directive this tick is running, if any, so the caller can tell an
        # idle script from one waiting on its own work in flight. Read from the
        # envelope it already built: a second GET would be a different moment.
        self.last_task = envelope.get("task")
        # The body is the runner's §2.1 tick request, read from its actual
        # validation (agent-script-runner src/server.js:151-164), not invented
        # here. That function is the authority and runs BEFORE routing:
        #
        #   contract_version !== 1  -> 409, for every path
        #   game_id !== token's game -> 401, wrong_game_token
        #
        # `contract_version` was missing from the first version of this body and
        # every tick was refused with a 409 that read, in this agent's log, as
        # an ordinary runner failure -- the script fired and was turned away at
        # the door, and the planner quietly took the tick. The old comment here
        # cited `src/main.js:167-216`, a file that does not do this check, which
        # is how a required field came to be absent from the request that sends
        # it. Cite the code that validates, not the code that looks related.
        body = {
            "contract_version": 1,
            "game_id": self._game_id,
            "bot_id": self._bot,
            "script_revision": self._revision,
            "source": self._source,
            "snapshot": envelope,
            "memory": self._memory,
        }
        # Added only when asked, never as `false`: the runner tests
        # `body.dry === true`, and a live tick's body must stay byte-identical
        # to what every existing caller sends.
        if self._dry:
            body["dry"] = True

        # When no transport was injected, post to SCRIPT_RUNNER_URL. It is
        # deliberately NOT `api._post`: that helper prefixes MOD_API_URL, so it
        # would send script ticks to the game mod, which answers JSON and would
        # look like a script result. No runner configured means no script mode.
        poster = self._post if self._post is not None else _default_transport()
        if poster is None:
            # Two different misconfigurations, named apart so an operator does
            # not chase a dead runner when the token is what is missing.
            from config import SCRIPT_RUNNER_URL
            if (SCRIPT_RUNNER_URL or "").strip() and not runner_token():
                return False, [], [], no_token_detail()
            return False, [], [], no_runner_detail()
        result = call_runner(self._api, body, post=poster, dry=self._dry)
        # Recorded once, here, so every return path below reports the state of
        # the tick that was actually sent. Assigned before the branch rather
        # than in each arm: a new early return added later would otherwise
        # silently report `None` (or a stale value) for a real runner state.
        self.last_state = result.state

        if result.state != STATE_SCRIPT:
            # Timeout, refused, error -- every non-script state falls through.
            #
            # Except one: an error tick that CARRIED a result. A script can
            # report and then throw in the same tick (runner main.js:250-255
            # sends the result on the error branch for exactly this), and that
            # report is the case the "must not be silently dropped"
            # requirement names. Hold it, marked as a failure -- the script
            # threw, so its absent `done` flag must not read as success
            # (`failed=True` travels to the trigger via last_result).
            #
            # The caller is still told `handled=False`: the tick did not
            # succeed, so the planner runs. Holding the result is about what
            # the bot LEARNED this tick, not about who acts next.
            if result.failed and result.result:
                # `text` may be None: a script that calls api.result(null) then
                # throws sends {"text": null}, which cap_result reports as
                # (None, False) -- "no report", the same case as reporting
                # nothing at all (binding.js:253-258 says the two must agree).
                # Coercing it first with str() would turn None into the string
                # "None" and hold a phantom report the planner would read as the
                # bot's own words. Only coerce a value that is actually there.
                raw_text = result.result["text"]
                text, cut = cap_result(text=None if raw_text is None else str(raw_text))
                if text is not None:
                    self.last_result = {
                        "text": text,
                        "truncated": bool(result.result.get("truncated")) or cut,
                        # No verdict is READ here: the status already said
                        # this tick failed, and consulting the payload's
                        # `done` would let a half-written result claim
                        # success over the throw that ended it.
                        "ok": False,
                        # This is the ONLY place a result is marked as an
                        # error, because it is the only path where the
                        # runtime observed a failure (the runner's status).
                        # `ok: False` alone is ambiguous: a script reporting
                        # `{done: false}` is still WORKING, and says so
                        # through the same field. Carrying the reason lets the
                        # caller deliver an error only for a real one.
                        "error": True,
                    }
            return False, [], [], f"runner {result.state}: {result.detail}"

        # Hold what the script remembered. The runner returns `memory_out` as
        # BASE64 of the UTF-8 blob (contract §4.1; the encoding happens at
        # worker.js:81), and `decodeMemory` base64-decodes on the way in
        # (engine.js:1059), so it is sent back exactly as received. This was
        # write-only until M3-1b: nothing read `memory_out`, so every
        # `api.recall()` returned null in production while the test driver fed
        # the value back by hand.
        #
        # Only on a SCRIPT state: a fallback carries memory=None, and taking it
        # would wipe a good blob with an empty one on a single runner timeout.
        #
        # And only when the script actually remembered something. The runner
        # sets `memoryOut` ONLY on an `api.remember` call (binding.js:314) and
        # resets it to null at the start of every tick (binding.js:113), so a
        # successful tick that logs and returns without storing reports
        # `memory_out: null`. Assigning that cleared the STORE_ALL cooldown
        # stamp on every non-storing tick, and the next tick stored again --
        # measured on test 2026-11-19 as a dispatch every 2 ticks for 8 minutes
        # (M3-1e bug 1). The two nulls mean different things: None from a
        # fallback is "the call did not happen", null on a SCRIPT tick is "the
        # script chose not to write". Only the first may clear the blob.
        if result.memory is not None:
            self._memory = result.memory

        # The script's log lines, held for the caller to print. Set on the
        # SCRIPT path only: a fallback has no script logs, and carrying the
        # previous tick's lines forward would attribute them to this one.
        self.last_logs = result.logs
        self.last_logs_dropped = result.logs_dropped

        # What the script reported, held for the caller to hand to the planner.
        #
        # The runner already capped it and sent JSON text, so this is a HOLD,
        # not a second serialisation: cap_result() takes a Python object and
        # would quote a string that is already JSON, turning {"a":1} into
        # "{\"a\":1}". The text is re-cut against the same byte limit rather
        # than trusted, because binding.js capResult and this module must agree
        # about the limit and a silent disagreement would only ever surface as
        # an over-size string reaching the planner. Re-cutting in-range text
        # is a no-op.
        self._hold_result(result)

        # Two shapes meet here: the runner's and the binder's. Translate first,
        # then bind, keeping the runner's seq beside each bound action so the
        # dispatch log can carry it (M2 §8.2 evidence wants the matching seq).
        pairs, refusals, raw_deliveries = translate_runner_actions(result.actions)
        bound, bind_refusals = action_binding.bind_actions([b for b, _ in pairs])
        refusals = _number_bind_refusals(refusals, bind_refusals, pairs)
        # `say`/`send` are delivered, not bound. They are collected on the
        # instance for the caller rather than returned in the tuple: the tuple
        # is `(handled, actions, refusals, detail)` and widening it would touch
        # every caller for data only the dispatch path wants -- the same reason
        # last_logs is an attribute. A DRY tick collects NONE: its whole point
        # is that it carries no side effects, and a chat line or an inter-bot
        # message is the most visible side effect there is.
        if self._dry:
            self.last_deliveries = []
        else:
            self.last_deliveries, delivery_refusals = validated_deliveries(
                raw_deliveries)
            refusals = refusals + delivery_refusals
        # `bind_actions` returns `bound` in input order and names each refusal's
        # index, so the surviving seqs are the pairs whose index bind kept.
        rejected = {r["index"] for r in bind_refusals if "index" in r}
        self._last_action_seqs = [seq for i, (_, seq) in enumerate(pairs)
                                  if i not in rejected]
        if not bound and not self.last_deliveries:
            # The script ran and proposed nothing this agent can DO. That is
            # still a handled tick *if* the script genuinely said "do nothing";
            # but if every action was refused, falling through would let the
            # planner quietly do something else, which is the opposite of what
            # the script asked. Distinguish the two. A tick that only said
            # something is NOT this case: it has deliveries, and the trial of
            # 2026-11-20 22:21Z is what happens when a say-only script is read
            # as "all actions refused" -- the bot falls back to the planner and
            # never speaks.
            if refusals:
                return False, [], refusals, DETAIL_ALL_ACTIONS_REFUSED
            return True, [], [], "script chose silence"

        if not bound:
            return True, [], refusals, (
                f"{len(self.last_deliveries)} delivery(ies)")
        if self.last_deliveries:
            return True, bound, refusals, (
                f"{len(bound)} action(s), "
                f"{len(self.last_deliveries)} delivery(ies)")
        return True, bound, refusals, f"{len(bound)} action(s)"

    def _hold_result(self, result):
        """Keep what the script reported, for the caller to hand to the planner.

        The runner sends the report already serialised as JSON text and already
        capped, so this is a HOLD and not a second serialisation -- passing the
        text as a *value* to cap_result() would serialise it twice and turn
        {"a":1} into the string "{\\"a\\":1}".

        The text is nonetheless re-cut against the same byte limit rather than
        trusted: binding.js capResult and cap_result() here must agree about the
        limit, and a silent disagreement would only ever show up as an over-size
        string reaching the planner. Re-cutting in-range text is a no-op.
        """
        reported = result.result
        if not (reported and reported.get("text") is not None):
            return
        text, cut = cap_result(text=str(reported["text"]))
        if text is not None:
            self.last_result = {"text": text,
                                "truncated": bool(reported.get("truncated")) or cut,
                                "ok": result_verdict(text)}

    def _build_snapshot(self):
        """Return `(envelope, errors)` -- an ENVELOPE on both paths.

        The two paths used to disagree, and the one production takes was the
        wrong shape. `SnapshotCache.get` returns `(envelope, errors)`; a bare
        `build_state` returns `(state, errors)`. Unpacked at the call site as
        `envelope, snap_errors`, the uncached path therefore put a raw state
        object on the wire with no `state` key -- and the script reads
        `snapshot.state.<field>` (scout.js:65), so EVERY field it touched was
        undefined: inventory, health, position, task. Measured on TEST
        2026-11-19, Scout logged "inventory empty" every tick for eight
        minutes while holding 16 cobblestone, and the agent-side reads were
        correct the whole time. The bot was not misreporting; the envelope was
        missing.

        The agent builds `ScriptTick` with no cache (agent.py:2881), so that
        wrong path was the only one production ever ran. Wrap here rather than
        requiring a cache: the cache is an optimisation, and a shape that
        depends on whether it is present is a bug waiting for a flag change.

        `tick` and `task` are supplied the same way `SnapshotCache.get` does,
        for the same reason it documents: the envelope and the state are
        separate objects, and leaving `task=` unset makes `snapshot.task` None
        on every tick whatever the bot is doing.
        """
        if self._cache is not None:
            return self._cache.get(self._bot)
        state, errors = snapshot_mod.build_state(self._api, self._bot)
        tick = self._tick_count = getattr(self, "_tick_count", 0) + 1
        envelope = snapshot_mod.build_envelope(state, tick=tick,
                                               task=state.get("task"))
        return envelope, errors

    def refresh(self):
        """Force the next tick to rebuild the snapshot (after an action lands)."""
        if self._cache is not None:
            self._cache.invalidate(self._bot)
