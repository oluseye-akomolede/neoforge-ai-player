#!/usr/bin/env bash
# Build the case-set ConfigMap for the evals scoring Job.
#
# The corpus copy is NOT in git and must not be committed. This script turns it
# into a case set in a temp dir and then into a ConfigMap; the case set itself
# is never committed either. Only this generator, and the Job that consumes the
# ConfigMap, are tracked.
#
# Run from the repo root on this VM. kubectl is not installed here: the apply
# step runs on controlplane (see the echo at the end).
set -euo pipefail

CORPUS=${CORPUS:-$HOME/minecraft-evals-corpus}
# 25, matching the 11-14 baseline the before/after report is signed against.
# Affordable only because the set ships as TWO ConfigMaps: at N=25 all three
# kinds in one map are 1312167 B encoded (over the 1MiB cap) but split they
# are 845323 B (exec) and 466844 B (plan+replan).
N=${N:-25}
OUT=${OUT:-$(mktemp -d)}
NAMESPACE=${NAMESPACE:-ci}
# Names are all overridable so the before/after legs can coexist. The lead
# runs two: the SAME case ConfigMaps for both legs (they are the shared
# artifact) and a DIFFERENT code ConfigMap per leg (that is the variable under
# test). Defaults reproduce a single baseline run.
#
#   exec   ConfigMap -> $NAME          (default evals-scout-cases)
#   plan+replan      -> $REBUILD_NAME  (default $NAME-rebuild)
#   code tar         -> $CODE_NAME     (default evals-code)
NAME=${NAME:-evals-scout-cases}
REBUILD_NAME=${REBUILD_NAME:-$NAME-rebuild}
CODE_NAME=${CODE_NAME:-evals-code}

if [ ! -d "$CORPUS" ]; then
  echo "no corpus at $CORPUS (set CORPUS=...)" >&2
  exit 1
fi

echo "extracting from $CORPUS (n=$N per kind) -> $OUT/cases"
mkdir -p "$OUT/cases"
python3 agent/output_evals/run.py \
  --config agent/output_evals/config.example.yaml \
  --trajectory-dir "$CORPUS" \
  --cases-out "$OUT/cases" \
  --out "$OUT/report.json" \
  --per-kind "$N" \
  --rebuild-from-source \
  --dry-run >"$OUT/extract.log" 2>&1

echo "case counts:"
wc -l "$OUT"/cases/*.jsonl

# Two ConfigMaps: exec on its own, plan+replan on theirs.
#
# The cap is per ConfigMap, on the base64-encoded DATA -- 4/3 the raw bytes
# plus a newline per 76-char chunk. At N=25 all three kinds together are
# 1312167 B encoded and the apply would be rejected on controlplane after
# this script printed success; split, exec is 845323 B and plan+replan are
# 466844 B, both under. Exec is the larger half only because its recorded
# prompts are longer -- the rebuild never touches those cases, so keeping them
# here bought nothing but budget.
check_cm() {   # check_cm <label> <files...>
  local label=$1; shift
  local enc raw
  raw=$(cat "$@" | wc -c)
  enc=$(python3 - "$@" <<'EOF'
import base64, sys
print(sum(len(base64.encodebytes(open(f, "rb").read())) for f in sys.argv[1:]))
EOF
)
  echo "  $label: $raw raw, $enc encoded"
  if [ "$enc" -gt 1048576 ]; then
    echo "REFUSED: $label is $enc B encoded, over the 1MiB ConfigMap limit." >&2
    echo "Lower N (currently $N) and re-run." >&2
    exit 1
  fi
}
echo "case-set sizes (cap 1048576 each):"
check_cm "$NAME (exec)"             "$OUT/cases/exec.jsonl"
check_cm "$REBUILD_NAME (plan+replan)" "$OUT/cases/plan.jsonl" "$OUT/cases/replan.jsonl"

# Code ConfigMap. A ConfigMap flattens paths to single keys, so a nested
# package cannot be mounted as a directory of directories. Ship one tar key and
# let the Job's init step extract it: exact paths survive, and there is no
# cleverness about path rewriting to get wrong. 32KB of source, well under the
# same 1MiB cap.
echo "packing code into $OUT/code.tar"
mkdir -p "$OUT/code/output_evals/scorers"
cp agent/output_evals/*.py "$OUT/code/output_evals/"
cp agent/output_evals/scorers/*.py "$OUT/code/output_evals/scorers/"
# --rebuild-from-source formats the CURRENT prompts, so the Job must run the
# prompt module THIS commit carries. Without it run.py would import the
# l3_planner beside the image's /opt/aibot-agent -- the deployed copy, which
# is neither the before nor the after leg this script is asked to measure.
# Only the two modules the rebuild EXECUTES: l3_planner for the prompt text and
# its format call, plan_schema for the Plan/Subtask classes it formats in. The
# rest of l3_planner's imports -- api, trajectory_log, brain, config -- resolve
# to the image's own copies at the end of PYTHONPATH, which is the same
# arrangement the scorers already rely on for `action_binding`.
#
# Stated plainly because it bounds what the leg claims: the PROMPT is from this
# commit, the surrounding agent package is the image's. A difference between
# the two that matters would show up in the rebuilt-vs-recorded comparison on
# the first dry run, not silently.
cp agent/l3_planner.py agent/plan_schema.py "$OUT/code/output_evals/"
# The run config travels with the code: it IS the yardstick the report is
# signed against, so a case set scored with a different model must be a visible
# change to this file, not a hidden flag on the Job.
#
# The endpoint is written HERE, into the file, rather than injected as env in
# the Job. The Job has no business rewriting the yardstick it is scored against;
# if the report says one endpoint and the env supplied another, the number is
# signed against something the artifact does not describe. The in-cluster
# address below is a service name, not a credential.
ENDPOINT=${ENDPOINT:-http://ollama-l3.minecraft-test.svc.cluster.local:11434}
MODEL=${MODEL:-qwen3-coder:30b}
# Whether the runner lets the served model think. Emitted HERE, into the file,
# for the same reason as endpoint and model: the generated config IS the
# yardstick, so a think-on leg must be a visible change to this file rather than
# a hidden flag. Omitting the key would make the runner take its default and the
# report would look honest while measuring think-off.
THINK=${THINK:-false}
case "$THINK" in
  true|false) ;;
  *) echo "REFUSED: THINK must be true or false, got '$THINK'." >&2
     echo "A quoted string or a number would read as thinking on." >&2
     exit 1 ;;
esac
{
  echo "# Generated by evals/make-evals-configmap.sh. This file IS the yardstick:"
  echo "# the same case set re-run against another model is a change to these lines."
  echo "endpoint: $ENDPOINT"
  echo "model: $MODEL"
  echo "timeout: 120"
  echo "concurrency: 1        # fixed: the local model is shared with the fleet"
  echo "think: $THINK"
} >"$OUT/code/output_evals/config.yaml"
echo "  $(find "$OUT/code" -name '*.py' | wc -l) python files, $(du -sb "$OUT/code" | cut -f1) B"
( cd "$OUT/code" && tar cf "$OUT/code.tar" output_evals )
echo "  code.tar $(wc -c <"$OUT/code.tar") B"

# There is deliberately NO kubectl branch here. kubectl is not installed on this
# VM by design, so a branch gated on `command -v kubectl` is a branch that only
# ever fires where nobody can read this script -- and it drifted: it created ONE
# ConfigMap from the whole cases directory (the unsplit 1312167 B set the guard
# refuses) and never created $REBUILD_NAME at all. Printing the commands instead
# means the one shape we can inspect here is the only shape that exists.
echo "artifacts ready under $OUT (code.tar $(wc -c <"$OUT/code.tar") B)."
echo "Build and apply all three ConfigMaps on controlplane:"
echo "  ssh controlplane 'mkdir -p /tmp/evals-artifacts/cases'"
echo "  scp $OUT/cases/exec.jsonl $OUT/cases/plan.jsonl $OUT/cases/replan.jsonl controlplane:/tmp/evals-artifacts/cases/"
echo "  scp $OUT/code.tar controlplane:/tmp/evals-artifacts/"
# The create/replace below is deliberately NOT `create --dry-run | kubectl apply`.
# Two reasons, both hit on the 11-14 run:
#  1. client-side apply stores the whole manifest in a last-applied annotation
#     capped at 262144 B, so a ~600 KB ConfigMap dies with "metadata.annotations:
#     Too long". --server-side stores no such annotation.
#  2. apply is a merge: it never removes keys absent from the new manifest, so
#     the 11-14 unsplit map kept its plan.jsonl/replan.jsonl keys inside $NAME
#     after the split. The Job survives that only because its volume lists
#     items: [exec.jsonl]; anything reading the whole map would not.
# delete-then-create makes the ConfigMap exactly what we just built, which is
# what the before/after comparison assumes.
echo "  ssh controlplane 'kubectl delete configmap $NAME $REBUILD_NAME $CODE_NAME -n $NAMESPACE --ignore-not-found'"
echo "  ssh controlplane 'kubectl create configmap $NAME -n $NAMESPACE --from-file=exec.jsonl=/tmp/evals-artifacts/cases/exec.jsonl'"
echo "  ssh controlplane 'kubectl create configmap $REBUILD_NAME -n $NAMESPACE --from-file=plan.jsonl=/tmp/evals-artifacts/cases/plan.jsonl --from-file=replan.jsonl=/tmp/evals-artifacts/cases/replan.jsonl'"
echo "  ssh controlplane 'kubectl create configmap $CODE_NAME -n $NAMESPACE --from-file=code.tar=/tmp/evals-artifacts/code.tar'"
echo "  # if you must re-apply over an existing map instead, use --server-side --force-conflicts"
echo "  # (client-side apply fails over 262144 B on the last-applied annotation)."
