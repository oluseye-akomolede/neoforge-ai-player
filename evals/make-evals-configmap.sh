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
# 19, not 30: with --rebuild-from-source the case set carries BOTH the
# recorded prompt and the rebuilt one, which roughly doubles it. Measured over
# the 11-14 corpus, N=19 is 991052 B and N=20 is 1042935 B, so 20 fits today
# with under 6 KB of slack -- too little to survive a case gaining a sentence.
# 19 keeps ~57 KB of headroom under the 1MiB ConfigMap cap.
N=${N:-14}
OUT=${OUT:-$(mktemp -d)}
NAMESPACE=${NAMESPACE:-ci}
NAME=${NAME:-evals-scout-cases}
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

BYTES=$(cat "$OUT"/cases/*.jsonl | wc -c)
# The 1MiB cap is on the ConfigMap's encoded DATA, and kubectl base64-encodes
# every value: 4/3 the raw bytes, plus a newline per 76-char chunk. Measuring
# the raw bytes undercounts by a third -- at N=25 the raw set was 1.23 MB so
# the old check passed it, while the ConfigMap was 1.32 MB and the apply would
# have been rejected on controlplane. Measured the way the API server counts.
ENCODED=$(python3 - "$OUT/cases" <<'EOF'
import base64, glob, os, sys
total = sum(len(base64.encodebytes(open(f, "rb").read()))
            for f in glob.glob(os.path.join(sys.argv[1], "*")))
print(total)
EOF
)
echo "case-set bytes: $BYTES raw, $ENCODED encoded (cap 1048576)"
if [ "$ENCODED" -gt 1048576 ]; then
  echo "REFUSED: encoded case set is $ENCODED B, over the 1MiB ConfigMap limit." >&2
  echo "Lower N (currently $N) and re-run: N=14 fits, N=15 leaves under 10KB." >&2
  exit 1
fi

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

if command -v kubectl >/dev/null 2>&1; then
  kubectl create configmap "$NAME" \
    --namespace "$NAMESPACE" \
    --from-file="$OUT/cases" \
    --dry-run=client -o yaml >"$OUT/$NAME.yaml"
  echo "wrote $OUT/$NAME.yaml"
  echo "apply on controlplane:"
  echo "  scp $OUT/$NAME.yaml controlplane:/tmp/ && ssh controlplane 'kubectl apply -f /tmp/$NAME.yaml'"
else
  # kubectl is not installed on this VM by design (kubectl runs on
  # controlplane). The case set and code tar are complete and verified against
  # the size cap; only the manifest wrap is left, and it is one command there.
  echo "kubectl not found here (expected; it runs on controlplane)."
  echo "artifacts ready under $OUT (cases $BYTES B, code.tar $(wc -c <"$OUT/code.tar") B)."
  echo "Build and apply both ConfigMaps on controlplane:"
  echo "  scp -r $OUT/cases $OUT/code.tar controlplane:/tmp/evals-artifacts/"
  echo "  ssh controlplane 'kubectl create configmap $NAME -n $NAMESPACE --from-file=/tmp/evals-artifacts/cases --dry-run=client -o yaml | kubectl apply -f -'"
  echo "  ssh controlplane 'kubectl create configmap $CODE_NAME -n $NAMESPACE --from-file=/tmp/evals-artifacts/code.tar --dry-run=client -o yaml | kubectl apply -f -'"
fi
