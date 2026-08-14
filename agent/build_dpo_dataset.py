"""Build a TRL-format DPO dataset from the RL trajectory log + plan archive.

v11 R3 step 1. DPO needs `(prompt, chosen, rejected)` triples where `chosen`
and `rejected` are two responses to the *same* task, one of which succeeded and
one of which failed. This module extracts those from two sources:

1. **Replan-refinement pairs** (primary, cleanest signal) — within one
   `(plan_ref, subtask_id)`, a call whose outcome is `satisfied=false` followed
   by a later call whose outcome is `satisfied=true` is the classic
   "L3 re-planned and got it right" pair: the failed response is `rejected`,
   the later successful response is `chosen`.

2. **Near-task cross-plan pairs** (secondary, fills out volume) — a failed
   subtask and a complete subtask from *different* plans whose normalized
   description + criteria match are paired, giving `rejected` = failed
   directives and `chosen` = complete directives.

The prompt for a pair is the successful call's `prompt_user` (what L3 was
actually asked). Responses are the verbatim `response_raw` for trajectory pairs
and the JSON directive list for archive pairs.

Honesty guard: this only reports what it actually found. With one day of
trajectory data the output is small; that is a *data-volume* signal, not a bug.
Run it repeatedly as the trajectory log accumulates and the dataset grows.

Usage:
    python3 build_dpo_dataset.py [--trajectory-dir DIR] [--plans-dir DIR] \
        [--out dpo_dataset.jsonl]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import defaultdict


def _normalize(text: str) -> str:
    """Collapse numbers and whitespace so near-identical tasks key together."""
    return re.sub(r"\d+", "#", (text or "").lower().strip())


# ── trajectory source ────────────────────────────────────────────────────────

def _iter_trajectory_records(traj_dir: pathlib.Path):
    if not traj_dir.is_dir():
        return
    for p in sorted(traj_dir.glob("trajectory-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def replan_pairs(traj_dir: pathlib.Path) -> list[dict]:
    """Replan-refinement DPO pairs from the trajectory log.

    Joins call → outcome on call_id, groups by (plan_ref, subtask_id), and for
    each group pairs an earlier failed call with a later successful call.
    """
    calls: dict[str, dict] = {}
    outcomes: dict[str, bool] = {}
    for r in _iter_trajectory_records(traj_dir):
        if r.get("type") == "call":
            calls[r["call_id"]] = r
        elif r.get("type") == "outcome" and r.get("call_id"):
            outcomes[r["call_id"]] = bool(r.get("satisfied"))

    by_group: dict[tuple, list[dict]] = defaultdict(list)
    for cid, c in calls.items():
        if cid not in outcomes:
            continue
        by_group[(c.get("plan_ref"), c.get("subtask_id"))].append(
            {**c, "_satisfied": outcomes[cid]}
        )

    pairs: list[dict] = []
    for calls_in_group in by_group.values():
        calls_in_group.sort(key=lambda c: c.get("ts", ""))
        for i, fail in enumerate(calls_in_group):
            if fail["_satisfied"]:
                continue
            for win in calls_in_group[i + 1:]:
                if win["_satisfied"] and win.get("response_raw"):
                    pairs.append({
                        "prompt": win.get("prompt_user", ""),
                        "chosen": win.get("response_raw", ""),
                        "rejected": fail.get("response_raw", ""),
                        "source": "trajectory",
                    })
                    break  # one rejected per failed call
    return pairs


# ── archive source ────────────────────────────────────────────────────────────

def _iter_archive(plans_dir: pathlib.Path):
    archive = plans_dir / "archive"
    if not archive.is_dir():
        return
    for p in archive.glob("*.json"):
        try:
            yield json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue


def near_task_pairs(plans_dir: pathlib.Path) -> list[dict]:
    """Cross-plan near-task pairs: failed vs complete subtasks whose normalized
    description + criteria match."""
    failed: dict[str, list[dict]] = defaultdict(list)
    complete: dict[str, list[dict]] = defaultdict(list)

    for plan in _iter_archive(plans_dir):
        for s in plan.get("subtasks", []):
            if not s.get("directives"):
                continue
            key = _normalize(s.get("description", "")) + " || " + _normalize(
                s.get("criteria", "")
            )
            status = s.get("status")
            if status == "failed":
                failed[key].append(s)
            elif status == "complete":
                complete[key].append(s)

    pairs: list[dict] = []
    for key in failed:
        if key not in complete:
            continue
        for fail_s in failed[key]:
            win_s = complete[key][0]
            pairs.append({
                "prompt": (
                    f"{win_s.get('description', '')} — {win_s.get('criteria', '')}"
                ).strip(" —"),
                "chosen": json.dumps(win_s["directives"], sort_keys=True),
                "rejected": json.dumps(fail_s["directives"], sort_keys=True),
                "source": "archive",
            })
    return pairs


def build(traj_dir: pathlib.Path, plans_dir: pathlib.Path) -> list[dict]:
    return replan_pairs(traj_dir) + near_task_pairs(plans_dir)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trajectory-dir", default=None)
    ap.add_argument("--plans-dir", default=None)
    ap.add_argument("--out", default="dpo_dataset.jsonl")
    ap.add_argument(
        "--min-pairs",
        type=int,
        default=0,
        help="Exit 2 (data-gated, not an error) if fewer than this many pairs "
             "are found — lets a scheduled Airflow run fail fast instead of "
             "training on a tiny dataset.",
    )
    args = ap.parse_args()

    traj = pathlib.Path(args.trajectory_dir) if args.trajectory_dir else None
    plans = pathlib.Path(args.plans_dir) if args.plans_dir else None

    pairs = build(traj, plans)
    by_src = defaultdict(int)
    for p in pairs:
        by_src[p["source"]] += 1

    out = pathlib.Path(args.out)
    with out.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"DPO pairs written: {len(pairs)} -> {out}")
    print(f"  by source: {dict(by_src)}")
    if not pairs:
        print("  WARNING: no pairs. Data volume is the blocker (see module doc).")
    if len(pairs) < args.min_pairs:
        print(f"DATA_GATED: {len(pairs)} pairs < --min-pairs {args.min_pairs} "
              f"— accumulate more trajectory data before training.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
