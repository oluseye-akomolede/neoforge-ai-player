#!/usr/bin/env python3
"""CLI entry point for the test harness."""

import argparse
import json
import sys
from pathlib import Path

from testing.harness import run_tests, load_test
from testing.world import list_worlds, destroy_world, TestWorld


def cmd_run(args):
    paths = [Path(p) for p in args.tests]
    for p in paths:
        if not p.exists():
            print(f"Error: test file not found: {p}", file=sys.stderr)
            sys.exit(1)

    results = run_tests(
        paths,
        registry_url=args.registry_url,
        registry_key=args.registry_key,
    )

    print(f"\n{'='*60}")
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"Results: {passed}/{total} passed")

    if args.json:
        output = []
        for r in results:
            output.append({
                "name": r.test_name,
                "passed": r.passed,
                "duration": round(r.duration, 1),
                "error": r.error,
                "steps": [
                    {
                        "step": sr.step,
                        "passed": sr.passed,
                        "duration": round(sr.duration, 1),
                        "details": sr.details,
                    }
                    for sr in r.step_results
                ],
            })
        print(json.dumps(output, indent=2))

    sys.exit(0 if passed == total else 1)


def cmd_list(args):
    worlds = list_worlds()
    if not worlds:
        print("No test worlds running.")
        return
    print(f"{'NAME':<30} {'PHASE':<12} {'CREATED':<22} {'TTL'}")
    print("-" * 75)
    for w in worlds:
        print(f"{w['name']:<30} {w['phase']:<12} {w['created']:<22} {w['ttl']}s")


def cmd_cleanup(args):
    worlds = list_worlds()
    if not worlds:
        print("No test worlds to clean up.")
        return
    for w in worlds:
        tw = TestWorld(name=w["name"].replace("test-world-", ""))
        tw.pod_name = w["name"]
        destroy_world(tw)
    print(f"Cleaned up {len(worlds)} test world(s).")


def main():
    parser = argparse.ArgumentParser(
        prog="test-harness",
        description="AI Bot Test Harness — run bot behavior tests in ephemeral NeoForge worlds",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run test definitions")
    p_run.add_argument("tests", nargs="+", help="Path(s) to YAML test definition files")
    p_run.add_argument("--registry-url", default=None, help="Bot registry URL")
    p_run.add_argument("--registry-key", default=None, help="Bot registry API key")
    p_run.add_argument("--json", action="store_true", help="JSON output")

    p_list = sub.add_parser("list", help="List running test worlds")
    p_cleanup = sub.add_parser("cleanup", help="Destroy all test world pods")

    args = parser.parse_args()
    {"run": cmd_run, "list": cmd_list, "cleanup": cmd_cleanup}[args.command](args)


if __name__ == "__main__":
    main()
