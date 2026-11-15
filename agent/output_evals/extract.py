"""Extract eval cases from the agent's own trajectory JSONL.

Source format is `agent/trajectory_log.py`: append-only `trajectory-YYYY-MM-
DD.jsonl`, three record types -- `call`, `outcome` (joined to its call by
`call_id`), `plan_close` (joined to plan/replan calls by `plan_ref`).

Rules that come from experience, not taste:

  - **Never pad.** A kind that the corpus cannot supply 30 cases for is
    reported with the count it has. Constructed cases would score the eval
    harness, not the model.
  - **An unlabelled call is not a success and not a failure.** It is counted
    in a `no_label` bucket and left out of the rate.
  - **Redact before writing.** The prompts carry tool output and chat text; a
    case file is committed-adjacent evidence and must not carry a credential.
  - **Era comes from the record.** `call.model` is the model that actually
    answered, so it is the only honest source for the sentence "only the input
    has an era".
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
from collections import defaultdict
from dataclasses import dataclass, field

SCORABLE = ("plan", "exec", "replan")
MIN_PER_KIND = 30

# Secret-shaped text that must never reach a case file or a report.
_SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{12,}"), r"\1<redacted>"),
    (re.compile(r"(?i)\b(rcon[\w.]*password|AIBOT_RCON_PASSWORD|[A-Z_]*(?:TOKEN|SECRET|PASSWORD|API_KEY))"
                r"\s*[=:]\s*\S+"), r"\1=<redacted>"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "<redacted-blob>"),
]


def redact(text):
    if not isinstance(text, str):
        return text
    out = text
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


# -- reading ---------------------------------------------------------------

def trajectory_dir(explicit=None):
    """Where the recordings live. Config/env first, never hardcoded."""
    if explicit:
        return pathlib.Path(explicit)
    env = os.environ.get("AIBOT_TRAJECTORY_DIR")
    if env:
        return pathlib.Path(env)
    raise FileNotFoundError(
        "no trajectory directory: pass --trajectory-dir or set AIBOT_TRAJECTORY_DIR"
    )


def read_records(directory):
    """All records, in file order (one file per UTC day)."""
    d = pathlib.Path(directory)
    if not d.is_dir():
        raise FileNotFoundError(f"trajectory directory not found: {d}")
    records, bad = [], 0
    for path in sorted(d.glob("trajectory-*.jsonl")):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(rec, dict):
                    records.append(rec)
                else:
                    bad += 1
    return records, bad


# -- joining ---------------------------------------------------------------

@dataclass
class Case:
    kind: str
    call_id: str
    bot: str
    model: str
    prompt_system: str
    prompt_user: str
    world_state_summary: str
    recorded_output: str
    label: str            # "satisfied" | "unsatisfied" | "complete" | "incomplete" | ""
    label_source: str     # "outcome" | "plan_close" | ""
    # -- rebuild-from-source leg (output_evals/sysprompt.py) ----------------
    # Where THIS case's system prompt came from. Only `synthesised` cases carry
    # a prompt no agent call ever sent: their response is a hand-written
    # fixture, so they can be scored but their prompt cannot be rebuilt.
    source: str = ""
    # What the rebuild changed. "" = the leg did not run on this case.
    # True/False are the answer; None means not comparable (see sysprompt.differs).
    prompt_differs: bool | None = None
    prompt_diff: str = ""
    recorded_prompt_system: str = ""   # the original, kept for the comparison
    recorded_plan: dict = field(default_factory=dict)      # replan only
    recorded_subtask: dict = field(default_factory=dict)   # replan only


@dataclass
class Census:
    total_calls: dict = field(default_factory=lambda: defaultdict(int))
    outcomes: int = 0
    plan_closes: int = 0
    # status -> count across EVERY plan_close row, joined or not.
    plan_close_status: dict = field(default_factory=lambda: defaultdict(int))
    replayable: dict = field(default_factory=lambda: defaultdict(int))
    not_replayable: dict = field(default_factory=lambda: defaultdict(int))
    joined: dict = field(default_factory=lambda: defaultdict(int))
    no_label: dict = field(default_factory=lambda: defaultdict(int))
    cancelled: dict = field(default_factory=lambda: defaultdict(int))
    by_era: dict = field(default_factory=dict)   # kind -> {model: {calls, replayable, labelled}}
    days: set = field(default_factory=set)
    bad_lines: int = 0
    # The model the agent runs today; the shortfall is measured against it.
    # Empty means "no era named", which reads as 30 short. That is a LIBRARY
    # default, not a production mode: evalconfig requires `model` and raises
    # without it, and era keys are never empty so "" cannot collide with one.
    current_era: str = ""
    per_kind: int = MIN_PER_KIND   # n actually run; shortfall is measured against it
    # kind -> {label: count} for labels harvested from the recording.
    _labels: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))

    def _historical(self, kind):
        """Rate from recorded labels, and the denominator it is a rate of.

        A historical score answers 'how did this END', not 'how good was this
        output'. Reported with its n so it is never read as a replay result.
        """
        counts = dict(self._labels.get(kind, {}))
        scored = counts.get("satisfied", 0) + counts.get("unsatisfied", 0) \
            + counts.get("complete", 0) + counts.get("incomplete", 0)
        good = counts.get("satisfied", 0) + counts.get("complete", 0)
        return {
            "counts": counts,
            "n": scored,
            "pass": good,
            "rate": (good / scored) if scored else None,
            "attribution": "plan_close.status on plan_ref" if kind in ("plan", "replan")
                           else "outcome.satisfied on call_id",
            "note": "recorded outcome, not a replay score; cancelled excluded",
            # n is what is ATTRIBUTABLE to a call -- a closure whose plan_ref
            # no call carries cannot be scored against one. The corpus-wide
            # closure count is larger (plan_close rows: 238 complete / 115
            # failed / 6 cancelled), and quoting one against the other reads
            # as a discrepancy when it is two different denominators.
            "n_note": "closures joinable to a call; corpus-wide plan_close rows are more",
        }

    def report(self):
        kinds = {}
        for kind in SCORABLE:
            eras = self.by_era.get(kind, {})
            replay = self.replayable.get(kind, 0)
            kinds[kind] = {
                "calls": self.total_calls.get(kind, 0),
                # Replay pool: a call with a usable input. This is what a replay
                # run is sampled from, and it needs NO historical label -- the
                # replayed output is scored by the automatic checks.
                "replayable": replay,
                "not_replayable": self.not_replayable.get(kind, 0),
                # Label pool: a call whose recorded outcome is known. This is a
                # separate, historical score and a different question.
                "labelled": self.joined.get(kind, 0),
                "no_label": self.no_label.get(kind, 0),
                "cancelled": self.cancelled.get(kind, 0),
                # Historical verdict from the recorded label, which for a plan
                # is plan_close.status (complete/failed), joined on plan_ref.
                # This is the spec's weaker-attribution historical score: it
                # says the plan ENDED well, not that the model wrote it well.
                # Cancelled plans are excluded -- an abandoned run is not a
                # verdict on the planner.
                "historical": self._historical(kind),
                "by_era": {m: dict(v) for m, v in sorted(eras.items())},
                # The spec's shortfall is about the CURRENT era ("today:
                # replan, 21"), not about all eras. Measuring it against the
                # all-era pool reports 0 for replan (271 all-era) and hides
                # exactly the shortfall the precedence paragraph addresses.
                # Measured against the n actually RUN, not the default: at
                # n=25 a current-era pool of 21 is 4 short, not 9.
                "short_of_" + str(self.per_kind): max(
                    0, self.per_kind - eras.get(self.current_era, {}).get("replayable", 0)),
                "short_of_" + str(self.per_kind) + "_all_era": max(0, self.per_kind - replay),
            }
        return {
            "kinds": kinds,
            "outcomes": self.outcomes,
            "plan_closes": self.plan_closes,
            # Corpus-wide plan_close statuses, independent of the join. Stated
            # beside the per-kind historical n so the two denominators cannot
            # be mistaken for each other or reported as a discrepancy.
            "plan_close_status": dict(self.plan_close_status),
            "distinct_days": len(self.days),
            "bad_lines": self.bad_lines,
        }


def is_replayable(rec):
    """Can this call be replayed? It needs only a usable INPUT, not a label.

    A replay re-sends the recorded prompt to the model and scores the NEW
    output with the automatic checks, so the recorded outcome is irrelevant to
    whether the case can be run. What it does need is the user prompt (the
    actual ask) and a call that parsed; a call with no prompt cannot be re-sent,
    and one that failed to parse has no trustworthy input to replay.

    Deliberately does NOT look at prompt_system: only plan-phase calls carry it
    (exec calls leave it empty), so requiring it would silently drop every exec
    case -- the same defect this function exists to fix.
    """
    if not str(rec.get("prompt_user") or "").strip():
        return False
    parse_error = rec.get("parse_error")
    if parse_error:
        return False
    return True


def build_cases(records, current_era="", per_kind=MIN_PER_KIND):
    """(cases, census). Pure function of the records -- easy to test."""
    outcomes_by_call, close_by_plan = {}, {}
    calls = []
    census = Census(current_era=current_era, per_kind=per_kind)

    for rec in records:
        t = rec.get("type")
        if t == "outcome":
            cid = rec.get("call_id")
            if cid:
                outcomes_by_call[cid] = rec
                census.outcomes += 1
        elif t == "plan_close":
            ref = rec.get("plan_ref")
            if ref:
                close_by_plan[ref] = rec
                census.plan_closes += 1
                census.plan_close_status[rec.get("status") or "unknown"] += 1
        elif t == "call":
            calls.append(rec)

    cases = []
    for rec in calls:
        kind = rec.get("phase")
        if kind not in SCORABLE:
            continue
        model = str(rec.get("model") or "unknown")
        census.total_calls[kind] += 1
        census.by_era.setdefault(kind, {}).setdefault(
            model, {"calls": 0, "replayable": 0, "labelled": 0})
        census.by_era[kind][model]["calls"] += 1
        ts = str(rec.get("ts") or "")
        if len(ts) >= 10:
            census.days.add(ts[:10])

        label, source = "", ""
        cancelled = False
        outcome = outcomes_by_call.get(rec.get("call_id"))
        if kind == "exec" and outcome is not None:
            label = "satisfied" if outcome.get("satisfied") else "unsatisfied"
            source = "outcome"
        elif kind in ("plan", "replan"):
            close = close_by_plan.get(rec.get("plan_ref"))
            if close is not None:
                status = str(close.get("status") or "")
                # `cancelled` is an abandoned run, not a failed plan. Scoring it
                # as incomplete charges the model for a decision it did not
                # make; it is dropped from the rate and counted on its own.
                # It must also NOT fall through to no_label, or the census
                # counts one plan twice and stops summing to its call count.
                if status == "cancelled":
                    cancelled = True
                    census.cancelled[kind] += 1
                elif status:
                    label = "complete" if status == "complete" else "incomplete"
                    source = "plan_close"

        if cancelled:
            # Cancelled affects only the HISTORICAL label: it is not a failure
            # and not a success, so it leaves that rate. It does NOT remove the
            # call from the replay pool -- the recorded input is still usable,
            # and a replay scores a fresh output, never the old verdict. Kicking
            # it out here silently shrank the current-era plan pool 37 -> 31.
            label, source = "", ""

        # Label buckets are exclusive: a call is labelled, cancelled, or has no
        # label -- exactly one, so they sum to the call count. A cancelled call
        # is already counted above and must not also land in no_label.
        if cancelled:
            pass
        elif label:
            census.joined[kind] += 1
            census.by_era[kind][model]["labelled"] += 1
            census._labels[kind][label] += 1
        else:
            census.no_label[kind] += 1

        if not is_replayable(rec):
            census.not_replayable[kind] += 1
            continue
        census.replayable[kind] += 1
        census.by_era[kind][model]["replayable"] += 1

        cases.append(Case(
            kind=kind,
            call_id=str(rec.get("call_id") or ""),
            bot=str(rec.get("bot") or ""),
            model=model,
            prompt_system=redact(rec.get("prompt_system") or ""),
            prompt_user=redact(rec.get("prompt_user") or ""),
            world_state_summary=redact(rec.get("world_state_summary") or ""),
            recorded_output=redact(rec.get("response_raw") or ""),
            label=label,
            label_source=source,
            source=str(rec.get("source") or ""),
        ))
    return cases, census


def take_era_first(cases, current_era, n=MIN_PER_KIND, seed=0):
    """Take up to `n` cases for one kind: current-era inputs first, then older.

    Stratified across bots by round-robin so one busy bot cannot supply the
    whole sample. Deterministic for a given (cases, seed) so a report can be
    reproduced. Returns (taken, {era: k}).
    """
    current = [c for c in cases if c.model == current_era]
    older = [c for c in cases if c.model != current_era]

    def stratify(pool):
        by_bot = defaultdict(list)
        for c in pool:
            by_bot[c.bot or "?"].append(c)
        for lst in by_bot.values():
            lst.sort(key=lambda c: (c.call_id, c.bot))
        out, bots = [], sorted(by_bot)
        i = 0
        while any(by_bot.values()):
            b = bots[i % len(bots)]
            if by_bot[b]:
                out.append(by_bot[b].pop(0))
            i += 1
        return out

    picked = stratify(current)[:n]
    if len(picked) < n:
        picked += stratify(older)[:n - len(picked)]
    tally = defaultdict(int)
    for c in picked:
        tally[c.model] += 1
    return picked, dict(tally)


def write_cases(cases_by_kind, out_dir):
    """Write one jsonl per kind. Returns {kind: {"path", "bytes"}}.

    The byte size is reported back because the case set ships as a ConfigMap
    and the API server caps one at 1MiB across all keys: the size is a
    property of the artifact that has to be stated, not discovered at apply.
    """
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = {}
    for kind, cases in cases_by_kind.items():
        path = out / f"{kind}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for c in cases:
                f.write(json.dumps(c.__dict__, sort_keys=True) + "\n")
        written[kind] = {"path": str(path), "bytes": path.stat().st_size}
    return written


def read_cases_dir(directory):
    """Load a case set previously written by `write_cases`.

    The scoring Job gets its cases through a ConfigMap and has no corpus and no
    PVC, so this is the inverse of `write_cases` and must stay field-for-field
    compatible with it. A missing kind is not an error: a kind the corpus could
    not supply simply is not scored, which the report states.
    """
    d = pathlib.Path(directory)
    if not d.is_dir():
        raise FileNotFoundError(f"cases directory not found: {d}")
    by_kind = {}
    for path in sorted(d.glob("*.jsonl")):
        cases = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                cases.append(Case(**json.loads(line)))
        by_kind[path.stem] = cases
    return by_kind
