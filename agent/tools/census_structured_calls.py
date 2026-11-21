"""Census of every agent function that asks for a structured reply and parses it.

Why this exists: the rule "every structured call checks done_reason before
parsing" was first written with a scope sentence that enumerated six call sites.
Two independent censuses then disagreed on the population before agreeing on
nine, with one guarded. A hand-written list is how a MUST ends up not covering
its own quantifier, and the misses were not obscure -- three of them substitute
a plausible result on a parse failure, so a truncation there becomes an answer
that looks like work.

Known limit, deliberate: requests_json_format matches the literal '"format"' in
the source segment, so it sees the dict form only. A call written as a kwarg --
client.chat(model=m, format="json") -- is NOT matched, and this file cannot see
it. Measured, not assumed: a probe in that form left the census at
"functions=9 guarded=1 unguarded=8", rc=0, with the probe absent from the rows.

So the gate does not red on a kwarg-form call. It is silent about it. That is
why this limit is written down rather than left to judgement: if the codebase
ever moves to kwargs, EXPECTED_SOURCES will keep passing while the population it
claims to count has shrunk underneath it. Widen the detector and re-derive the
expected counts in the same commit. Do not narrow it into a filter that quietly
changes what counts.

Run: python3 -B agent/tools/census_structured_calls.py
Exit 1 if the guarded count differs from EXPECTED_GUARDED, so a new unguarded
call cannot be added without this file being looked at.
"""
import ast
import pathlib
import sys

# Files that are not part of the live request path. Listed explicitly so that
# excluding one is a visible decision rather than a filter that quietly grows.
OUT_OF_SCOPE = {
    "run.py",  # output_evals harness; never runs against a bot
}

EXPECTED_SOURCES = 9
EXPECTED_GUARDED = 9   # every census site guarded by ensure_not_truncated or
                       # its own inline read (call_plan)


def guards_done_reason(fn: ast.AST) -> bool:
    """True only if the function READS done_reason out of a response.

    A bare search for the string counts docstrings and neighbouring-constant
    comments as checks -- that is exactly how `classify_message` and
    `brain.think` were miscounted as safe. The check this looks for is a
    subscript of a *parsed* body: `body.get("done_reason")` or
    `body["done_reason"]`, not the name appearing anywhere in the source.
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and sl.value == "done_reason":
                return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("get", "pop") and node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.Constant) and a0.value == "done_reason":
                    return True
        # The shared guard. A call to it IS a read of done_reason: the function
        # lives in config.py and raises on done_reason == "length" before any
        # parse. Recognised by name rather than by opening config.py, so this
        # stays a cheap AST pass; the name is pinned by
        # test_the_shared_guard_actually_checks_done_reason, which fails if the
        # helper ever stops reading the field.
        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if fname == "ensure_not_truncated":
                return True
    return False


def parses_json(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name in ("loads", "load"):
                return True
    return False


def requests_json_format(fn: ast.AST, src: str) -> bool:
    """True if the segment asks the model for JSON. Dict form only -- see the
    module docstring's "Known limit". A kwarg call is not matched, and nothing
    reds: the census simply does not see it. Checked, not assumed."""
    seg = ast.get_source_segment(src, fn) or ""
    return '"json"' in seg and '"format"' in seg


def main() -> int:
    rows = []
    for path in sorted(pathlib.Path("agent").rglob("*.py")):
        if "test" in path.name or "test" in path.parent.name:
            continue
        if path.name in OUT_OF_SCOPE:
            continue
        src = path.read_text()
        tree = ast.parse(src)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not requests_json_format(fn, src) or not parses_json(fn):
                continue
            rows.append((path.name, fn.name, fn.lineno, guards_done_reason(fn)))

    rows.sort(key=lambda r: (r[0], r[2]))
    for fname, fname_fn, lineno, guarded in rows:
        print(f"{fname:16} {fname_fn:20} :{lineno:<6} {'GUARDED' if guarded else 'UNGUARDED'}")

    guarded = sum(1 for r in rows if r[3])
    print(f"\nfunctions={len(rows)} guarded={guarded} unguarded={len(rows) - guarded}")
    if len(rows) != EXPECTED_SOURCES or guarded != EXPECTED_GUARDED:
        print(
            f"DRIFT: expected {EXPECTED_SOURCES} sources / {EXPECTED_GUARDED} guarded. "
            "If a call was added, add it to the requirement and task 4.1. If one "
            "was guarded, tick the task. Then update the constants above.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
