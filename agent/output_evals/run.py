"""Run an output eval: extract cases, replay them against the configured model,
score the new output, write a report.

The three ways this can lie, and what stops each:

  - **A dead instrument still prints a verdict.** The endpoint is checked before
    the first call and the run exits non-zero with no report if it does not
    answer for the configured model. (Same lesson as the soak's null
    checkpoints.)
  - **A missing measurement reads as a good one.** A case that cannot be scored
    is counted unscorable, never dropped and never passed.
  - **A rate over too few cases looks like a rate.** Every number carries its
    `n`, and a rate is withheld below `min_n` rather than printed with a note
    nobody reads.

Exit codes: 0 ok, 2 config/endpoint refused (no report written), 3 no cases,
9 the scorer surface did not load (no report written).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

if __package__ in (None, ""):        # run as a file, not a module
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from output_evals import evalconfig, extract, sysprompt   # noqa: E402
from output_evals.scorers import common as scenum      # noqa: E402
from output_evals.scorers import planner               # noqa: E402

MIN_N_FOR_RATE = 10
MARKED_GAP_POINTS = 15


def ask(cfg, system, user):
    """One replay call. (text, error). Ollama chat shape; no retries.

    No retries on purpose: a model that times out is a result about the model
    under test, not a transient to smooth over.
    """
    payload = {
        "model": cfg.model,
        "stream": False,
        "format": "json",
        # Top level, not inside `options`: Ollama reads it there, and a nested
        # value is silently ignored. From the eval config, not AIBOT_LLM_THINK:
        # the Job packs output_evals standalone and has no agent config or
        # environment. This is the site that measures a candidate model, so it
        # must be able to think on deliberately while the fleet keeps it off.
        "think": cfg.think,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        f"{cfg.endpoint}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    msg = body.get("message") if isinstance(body, dict) else None
    if not isinstance(msg, dict) or "content" not in msg:
        return None, "response carried no message.content"
    return msg["content"], None


class EmptyPrompt(RuntimeError):
    """A plan/replan case reached the model without a system prompt.

    Raised rather than counted: there is no verdict to record, because no
    question was asked. `main` turns it into a non-zero exit so a run that
    would have measured nothing is a visible failure instead of a report.
    """


def run(cfg, cases_by_kind, log=print, rebuild_applied=False):
    results = {}
    for kind, cases in cases_by_kind.items():
        scorer = planner.SCORERS.get(kind)
        if scorer is None:
            results[kind] = {"error": f"no scorer for kind {kind}"}
            continue
        counted = defaultdict(int)
        by_era = defaultdict(lambda: defaultdict(int))
        examples = []
        # Every fail is counted by reason, not just the first five shown. A
        # rate alone cannot say whether six fails are six shapes of wrong or one
        # repeated; the counts can, and they make a kind's passes (e.g. SKILL)
        # visible instead of hidden behind an aggregate.
        fail_reasons = defaultdict(int)
        # Directive counts by adherence, on every result and not only failures.
        # A SKILL answer with five extra directives scores identically to a
        # clean one, so without this the report cannot tell an answer that
        # obeyed "emit exactly ONE directive" from one that did not.
        directive_counts = defaultdict(int)
        # Answers that were a clarify or a refuse instead of the thing asked
        # for. These are neither silently passed nor merged into the fail
        # count: a refusal is a different result from a malformed plan, and a
        # report that lumps them together cannot say which the model did.
        declined = defaultdict(int)
        t0 = time.time()
        for i, c in enumerate(cases, 1):
            if rebuild_applied and (c.prompt_diff or "").startswith("unscorable"):
                # Not sent and not scored: replaying the RECORDED prompt here
                # would answer a different question from every other case in
                # the run and print its result under the same heading.
                verdict, reason = "unscorable", c.prompt_diff
                counted[verdict] += 1
                by_era[c.model][verdict] += 1
                by_era[c.model]["n"] += 1
                continue
            # Fail closed. A plan or replan case whose system prompt is empty
            # was never rebuilt, and sending it asks the model a question with
            # no instructions at all: the answer is scored as if the prompt had
            # been there. This is silent by construction -- an empty string is
            # a legal prompt_system -- so refuse the whole run instead of
            # recording verdicts nobody can interpret.
            #
            # recorded_prompt_system set + empty prompt_system is the deferred
            # shape: it means the case set expected the Job to rebuild and the
            # Job did not.
            if c.kind in ("plan", "replan") and not (c.prompt_system or "").strip():
                raise EmptyPrompt(
                    f"{c.kind} case {c.call_id} has an empty system prompt "
                    f"(recorded_prompt_system={'set' if c.recorded_prompt_system else 'empty'}"
                    f", rebuild_applied={rebuild_applied}). The case set ships "
                    f"without a rendered prompt; run with --rebuild-from-source.")
            text, err = ask(cfg, c.prompt_system, c.prompt_user)
            if err:
                verdict, reason = "unscorable", f"replay error: {err}"
            else:
                r = scorer(text)
                verdict, reason = r.verdict, r.reason
                n_dirs = (r.detail or {}).get("n")
                if isinstance(n_dirs, int):
                    directive_counts[n_dirs] += 1
                shape = (r.detail or {}).get("shape")
                if shape in ("clarify", "refuse"):
                    declined[shape] += 1
                if verdict == scenum.FAIL:
                    fail_reasons[reason or "(no reason given)"] += 1
                    if len(examples) < 5:
                        examples.append({"call_id": c.call_id, "bot": c.bot,
                                         "reason": reason,
                                         "output_head": (text or "")[:300]})
            counted[verdict] += 1
            by_era[c.model][verdict] += 1
            by_era[c.model]["n"] += 1
            if i % 10 == 0:
                log(f"  {kind}: {i}/{len(cases)}")
        n = sum(counted.values())
        rate = (counted["pass"] / n) if n else None
        era_rows = {}
        for era, d in sorted(by_era.items()):
            era_n = d["n"]
            era_rows[era] = {
                "n": era_n,
                "pass": d["pass"],
                "rate": (d["pass"] / era_n) if era_n else None,
                "rate_withheld": era_n < MIN_N_FOR_RATE,
            }
        drift = flag_drift(era_rows)
        results[kind] = {
            "n": n,
            "pass": counted["pass"],
            "fail": counted["fail"],
            "unscorable": counted["unscorable"],
            "rate": rate,
            "rate_withheld": n < MIN_N_FOR_RATE,
            "by_era": era_rows,
            "era_drift_flag": drift,
            "fail_reasons": dict(sorted(fail_reasons.items(),
                                        key=lambda kv: (-kv[1], kv[0]))),
            # Clarify/refuse counts, separate from fail and from pass. Present
            # and empty when none occurred -- an absent key is indistinguishable
            # from a report written by older code.
            "declined": dict(sorted(declined.items())),
            # How many directives each answer carried. "1" is adherence to the
            # prompt's "exactly ONE directive"; anything above it is a model
            # that obeyed in kind but not in count, and would otherwise score
            # identically to a clean answer.
            "directives_per_answer": dict(sorted(directive_counts.items())),
            "single_directive_rate": (
                directive_counts.get(1, 0) / sum(directive_counts.values())
                if directive_counts else None),
            "examples": examples,
            "seconds": round(time.time() - t0, 1),
        }
        log(f"{kind}: n={n} pass={counted['pass']} "
            f"rate={'(withheld)' if n < MIN_N_FOR_RATE else f'{rate:.3f}'}")
    return results


def flag_drift(era_rows):
    """Two eras, each with n>=10, differing by more than MARKED_GAP_POINTS."""
    usable = [(era, r) for era, r in era_rows.items()
              if r["n"] >= MIN_N_FOR_RATE and r["rate"] is not None]
    if len(usable) < 2:
        return {"flagged": False,
                "reason": f"fewer than two eras with n>={MIN_N_FOR_RATE}; not flagged"}
    rates = [r["rate"] for _, r in usable]
    gap = max(rates) - min(rates)
    if gap > MARKED_GAP_POINTS / 100:
        return {"flagged": True, "gap_points": round(gap * 100, 1),
                "note": "possible prompt-format drift between eras, not model quality"}
    return {"flagged": False, "gap_points": round(gap * 100, 1)}


def build_report(cfg, census, results, n_cases, run_params=None):
    return {
        "config": {"endpoint": cfg.endpoint, "model": cfg.model,
                   "config_path": cfg.path, "timeout": cfg.timeout,
                   "endpoint_from_env": cfg.endpoint_from_env,
                   "think": cfg.think,
                   "think_source": "file" if cfg.think_from_file else "default"},
        # Stated on the face of the report, not left to be inferred: what n was
        # run, how many cases that produced, and how big the set is. The lead
        # requires these three, and a shortfall is only meaningful against the
        # n actually run.
        "run_parameters": run_params or {},
        # Present only on a rebuild run. It is the difference between "today's
        # model on yesterday's prompt" and "today's prompt", and a report that
        # did not say which would make the two incomparable numbers look like
        # a trend.
        "rebuild_from_source": (run_params or {}).get("rebuild_from_source"),
        "corpus": census,
        "cases_per_kind": n_cases,
        "results": results,
        "notes": [
            "rates carry their n; a rate below the minimum n is withheld",
            "an unscorable case is a failed measurement, not a pass",
            "era flags compare rates of Inputs from different model eras "
            "answered by today's model",
            "'historical' is the recorded verdict joined from the corpus -- "
            "for plan/replan, plan_close.status on plan_ref (the spec's "
            "weaker-attribution score). It is NOT a replay result.",
        ],
    }


def precheck_scorers(planner_module=None):
    """Prove the scorer surface loads, or say why not. (ok, why).

    The Job packs `output_evals` standalone, but the scorers import from the
    AGENT package (`action_binding`, for the directive surface). If that import
    fails inside the Job, every case is scored `unscorable` and the run still
    exits 0 -- an instrument that measured nothing, printing a verdict. That
    happened at 18:38Z: 25/25 unscorable and a report that looked like a result.

    So the surface is loaded here, before any report can be written, and the
    caller exits 9 on failure. Checking the import is not enough on its own:
    `SCORERS` is asserted non-empty and keyed by the kinds the run will score,
    because a module that imports but registers nothing would pass an
    import-only check and still measure nothing.

    `planner_module` is injectable so the test can supply a stub whose surface
    fails to load, instead of blocking imports in `sys.modules`. Manipulating
    global import state made this test's outcome depend on how the module was
    first imported (discover `-s` vs `-t .`): the blocked names are not the
    only route to `action_binding`, so a real import could succeed inside a
    block that set them to None. Injection removes that from the test.
    """
    if planner_module is not None:
        planner = planner_module
    else:
        try:
            from output_evals.scorers import planner
        except Exception as e:
            return False, f"scorer surface failed to import: {type(e).__name__}: {e}"
    missing = [k for k in extract.SCORABLE if k not in planner.SCORERS]
    if missing:
        return False, f"scorer registry is missing {missing} (has {sorted(planner.SCORERS)})"
    # The decisive check, and the one an import-only version misses entirely:
    # _load_surface() SWALLOWS the action_binding failure and caches it, so the
    # module imports, SCORERS is fully populated, and every case then scores
    # unscorable while the run exits 0. That is the 18:38Z shape exactly. The
    # import succeeding proves nothing; the surface loading does.
    surface, err = planner._load_surface()
    if err:
        return False, f"scorer surface did not load: {err}"
    if not surface:
        return False, "scorer surface loaded empty"
    return True, "scorers load, register every kind, and resolve the action surface"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--trajectory-dir", default=None)
    ap.add_argument("--cases-in", default=None,
                    help="score a case set written by write_cases (ConfigMap); "
                         "no corpus read, no --trajectory-dir needed")
    ap.add_argument("--out", required=True, help="report path (.json)")
    ap.add_argument("--emit", action="store_true",
                    help="also print the report to stdout (for a Job's pod log)")
    ap.add_argument("--cases-out", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="extract and report the corpus only; no model calls")
    ap.add_argument("--rebuild-from-source", action="store_true",
                    help="send the CURRENT l3_planner system prompt instead of "
                         "the recorded one, for plan and replan cases. Without "
                         "it a replay measures the model against the prompt it "
                         "already answered, so no prompt edit can ever move a "
                         "number. A case whose values cannot be recovered from "
                         "the record is scored unscorable, never guessed.")
    ap.add_argument("--per-kind", type=int, default=None,
                    help=f"cases per kind (default {extract.MIN_PER_KIND}); lower it "
                         "when the case set must fit a 1MiB ConfigMap")
    args = ap.parse_args(argv)

    # Before config, before any model call, before any report: an instrument
    # that cannot load its scorers must not produce a verdict. Exit 9, distinct
    # from 2 (config/endpoint) and 3 (no cases), so a Job failure names which.
    ok, why = precheck_scorers()
    if not ok:
        print(f"refused: {why}", file=sys.stderr)
        print("refused: not scoring with a scorer surface that did not load",
              file=sys.stderr)
        return 9

    try:
        cfg = evalconfig.load_config(args.config)
    except evalconfig.ConfigError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2

    # A dry run extracts and reports the CASE SET; it makes no model calls, so
    # it does not probe the endpoint. Probing here and then continuing would
    # print a refusal the run did not honour -- a verdict the run never reached.
    if args.dry_run:
        print("endpoint: not probed (dry run: no model calls)")
    else:
        ok, why = evalconfig.check_endpoint(cfg)
        print(f"endpoint: {'ok' if ok else 'REFUSED'} - {why}")
        if not ok:
            print("refused: not writing a report from an endpoint that does "
                  "not answer for the configured model", file=sys.stderr)
            return 2

    if args.cases_in:
        try:
            by_kind = extract.read_cases_dir(args.cases_in)
        except FileNotFoundError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 4
        corpus = {"source": "case-set", "cases_dir": args.cases_in}
        tally = {}
        # Rebuild HERE, in the Job, from the l3_planner this code ConfigMap
        # carries. The case set is the same artifact for the before and after
        # legs; only the code ConfigMap changes, which is what makes the two
        # runs comparable. `sysprompt.rebuild` returns the case untouched for
        # kinds it does not own, so exec is unaffected.
        if args.rebuild_from_source:
            import l3_planner  # noqa: E402 - from the code ConfigMap, not the image
            print(json.dumps({"l3_planner": getattr(l3_planner, "__file__", "?")},
                             indent=2))
            skills = sysprompt.skills_from_env() or None
            counts = defaultdict(int)
            for kind, cases_in_kind in by_kind.items():
                for c in cases_in_kind:
                    try:
                        sysprompt.rebuild(c, l3_planner, skills=skills)
                        key = "rebuilt"
                    except sysprompt.Unscorable as e:
                        c.prompt_differs, c.prompt_diff = None, f"unscorable: {e}"
                        key = "unscorable"
                    counts[(kind, key)] += 1
            print(json.dumps({"rebuild_in_job": {f"{k}|{v}": n
                                                 for (k, v), n in counts.items()}},
                             indent=2))
    else:
        directory = extract.trajectory_dir(args.trajectory_dir)
        records, bad = extract.read_records(directory)
        # n actually run: the shortfall must be measured against THIS, not the
        # default. At n=25 a current-era pool of 21 is 4 short, not 9.
        per_kind = args.per_kind or extract.MIN_PER_KIND
        cases, census = extract.build_cases(records, current_era=cfg.model,
                                            per_kind=per_kind)
        census.bad_lines = bad
        corpus = census.report()
        print(json.dumps({"corpus": corpus}, indent=2))

        current = cfg.model
        by_kind, tally = {}, {}
        for kind in extract.SCORABLE:
            pool = [c for c in cases if c.kind == kind]
            picked, t = extract.take_era_first(pool, current, n=per_kind)
            by_kind[kind] = picked
            tally[kind] = t
    # The rebuild happens in the JOB, not here.
    #
    # The case ConfigMap is the before/after pair's SHARED input: both legs
    # read the same cases and differ only in the code ConfigMap, which is what
    # makes the comparison a controlled one. So extract time puts each case's
    # recorded prompt into `recorded_prompt_system` (the rebuild's input) and
    # leaves `prompt_system` empty for the Job to fill. Rendering the prompt
    # here instead would bake one commit's l3_planner into the shared artifact
    # and the "before" leg would silently run against "after" text.
    rebuild = None
    # Extract time only. With --cases-in the set is ALREADY the shared
    # artifact, and the rebuild above has just filled `prompt_system` from this
    # code ConfigMap. Deferring here as well would move the rebuilt text back
    # into `recorded_prompt_system` and blank `prompt_system`, so the Job would
    # rebuild the cases and then send "" to the model: a whole run of empty
    # prompts, reported as scored.
    if args.rebuild_from_source and not args.cases_in:
        for kind, picked in by_kind.items():
            for c in picked:
                if c.kind in ("plan", "replan") and c.prompt_system:
                    c.recorded_prompt_system = c.prompt_system
                    c.prompt_system = ""
        rebuild = {"applied": "deferred-to-job"}

    case_sizes = {}
    if args.cases_out:
        written = extract.write_cases(by_kind, args.cases_out)
        case_sizes = {k: v["bytes"] for k, v in written.items()}
        print("wrote:", {k: v["path"] for k, v in written.items()})

    n_cases = {k: len(v) for k, v in by_kind.items()}
    if sum(n_cases.values()) == 0:
        print("no replayable cases: nothing to score (every call lacked a usable input)",
              file=sys.stderr)
        return 3

    run_params = {
        # In --cases-in mode the set was built elsewhere, so per-kind is not
        # this run's parameter to claim; report the sizes that were loaded.
        "per_kind": per_kind if not args.cases_in else None,
        "per_kind_source": "cases-in (set built by write_cases)"
                           if args.cases_in else "sampled here",
        "cases_total": sum(n_cases.values()),
        "cases_bytes": sum(case_sizes.values()) if case_sizes else None,
        "cases_bytes_by_kind": case_sizes or None,
        "rebuild_from_source": rebuild,
    }
    if args.dry_run:
        report = {"config": {"endpoint": cfg.endpoint, "model": cfg.model,
                             "config_path": cfg.path,
                             "endpoint_from_env": cfg.endpoint_from_env,
                             "think": cfg.think,
                             "think_source": ("file" if cfg.think_from_file
                                              else "default")},
                  "run_parameters": run_params,
                  "corpus": corpus, "cases_per_kind": n_cases,
                  "results": {}, "dry_run": True,
                  "endpoint_probed": False,
                  "era_tally": tally}
    else:
        try:
            results = run(cfg, by_kind, rebuild_applied=bool(rebuild))
        except EmptyPrompt as e:
            # Nothing has been scored at this point, so there is no report to
            # write: a non-zero exit is the whole signal. Printed to stderr so
            # it survives even if a caller only keeps stdout.
            print(f"refused: {e}", file=sys.stderr)
            return 5
        report = build_report(cfg, corpus, results, n_cases, run_params)
        report["era_tally"] = tally

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    # Also to stdout. In the Job, --out is an emptyDir that dies with the pod,
    # so the pod log is the durable surface; a report that exists only on a
    # dead volume is a report nobody can read.
    if args.emit:
        print("--- report (json) ---")
        print(json.dumps(report, indent=2, sort_keys=True))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
