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

Exit codes: 0 ok, 2 config/endpoint refused (no report written), 3 no cases.
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

from output_evals import evalconfig, extract           # noqa: E402
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


def run(cfg, cases_by_kind, log=print):
    results = {}
    for kind, cases in cases_by_kind.items():
        scorer = planner.SCORERS.get(kind)
        if scorer is None:
            results[kind] = {"error": f"no scorer for kind {kind}"}
            continue
        counted = defaultdict(int)
        by_era = defaultdict(lambda: defaultdict(int))
        examples = []
        t0 = time.time()
        for i, c in enumerate(cases, 1):
            text, err = ask(cfg, c.prompt_system, c.prompt_user)
            if err:
                verdict, reason = "unscorable", f"replay error: {err}"
            else:
                r = scorer(text)
                verdict, reason = r.verdict, r.reason
                if verdict == scenum.FAIL and len(examples) < 5:
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


def build_report(cfg, census, results, n_cases):
    return {
        "config": {"endpoint": cfg.endpoint, "model": cfg.model,
                   "config_path": cfg.path, "timeout": cfg.timeout},
        "corpus": census,
        "cases_per_kind": n_cases,
        "results": results,
        "notes": [
            "rates carry their n; a rate below the minimum n is withheld",
            "an unscorable case is a failed measurement, not a pass",
            "era flags compare rates of Inputs from different model eras "
            "answered by today's model",
        ],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--trajectory-dir", default=None)
    ap.add_argument("--out", required=True, help="report path (.json)")
    ap.add_argument("--cases-out", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="extract and report the corpus only; no model calls")
    args = ap.parse_args(argv)

    try:
        cfg = evalconfig.load_config(args.config)
    except evalconfig.ConfigError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2

    ok, why = evalconfig.check_endpoint(cfg)
    print(f"endpoint: {'ok' if ok else 'REFUSED'} - {why}")
    if not ok and not args.dry_run:
        print("refused: not writing a report from an endpoint that does not "
              "answer for the configured model", file=sys.stderr)
        return 2

    directory = extract.trajectory_dir(args.trajectory_dir)
    records, bad = extract.read_records(directory)
    cases, census = extract.build_cases(records)
    census.bad_lines = bad
    corpus = census.report()
    print(json.dumps({"corpus": corpus}, indent=2))

    current = cfg.model
    by_kind, tally = {}, {}
    for kind in extract.SCORABLE:
        pool = [c for c in cases if c.kind == kind]
        picked, t = extract.take_era_first(pool, current)
        by_kind[kind] = picked
        tally[kind] = t
    if args.cases_out:
        print("wrote:", extract.write_cases(by_kind, args.cases_out))

    n_cases = {k: len(v) for k, v in by_kind.items()}
    if sum(n_cases.values()) == 0:
        print("no labelled cases: nothing to score", file=sys.stderr)
        return 3

    if args.dry_run:
        report = {"config": {"endpoint": cfg.endpoint, "model": cfg.model,
                             "config_path": cfg.path},
                  "corpus": corpus, "cases_per_kind": n_cases,
                  "results": {}, "dry_run": True,
                  "era_tally": tally}
    else:
        results = run(cfg, by_kind)
        report = build_report(cfg, corpus, results, n_cases)
        report["era_tally"] = tally

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
