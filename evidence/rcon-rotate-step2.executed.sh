#!/bin/bash
# RCON rotation, step 2: rotate the Secret. Never prints the value.
# Guard per RCON-ROTATION-PLAN.md 1(ii): trace and history off around the value,
# prior state remembered and restored (unset stays unset).
set -eu
NS=minecraft-test
SEC=minecraft-rcon

_xt=$(case $- in *x*) echo on;; *) echo off;; esac)
_hf=${HISTFILE+x}
_hv=${HISTFILE-}
set +x
case $- in *m*) set +o history;; esac
HISTFILE=/dev/null

NEW=$(head -c 24 /dev/urandom | xxd -p -c 48)

# Acceptance test: exactly 48 chars, pure hex. Refuse before writing anything.
if [ "${#NEW}" -ne 48 ]; then
  echo "REFUSED: generated length ${#NEW} is not 48"
  exit 2
fi
case "$NEW" in
  *[!0-9a-f]*) echo "REFUSED: generated value is not pure hex"; exit 2;;
esac

# Old fingerprint, for the report. Computed before the write.
OLD_FP=$(kubectl -n "$NS" get secret "$SEC" -o jsonpath='{.data.password}' \
         | base64 -d | sha256sum | cut -c1-16)
NEW_FP=$(printf '%s' "$NEW" | sha256sum | cut -c1-16)

kubectl -n "$NS" create secret generic "$SEC" \
  --from-literal=password="$NEW" \
  --dry-run=client -o yaml \
  | kubectl -n "$NS" apply -f - >/dev/null

# Read back from the cluster, not from $NEW: what the Secret actually holds.
WRITTEN_FP=$(kubectl -n "$NS" get secret "$SEC" -o jsonpath='{.data.password}' \
             | base64 -d | sha256sum | cut -c1-16)

# These fingerprints are for THIS run log and nowhere else. A 16-hex digest of a
# live credential is a cheap way to check a guess: do not paste this output into
# a plan, a row, a message or a note. The plan says what the scan established;
# the numbers stay here.
echo "old_fp=$OLD_FP"
echo "new_fp_generated=$NEW_FP"
echo "new_fp_in_cluster=$WRITTEN_FP"
if [ "$NEW_FP" = "$WRITTEN_FP" ]; then echo "write_verified=yes"; else echo "write_verified=NO"; fi
echo "new_len=${#NEW}"

unset NEW
[ "$_xt" = on ] && set -x
if [ -n "$_hf" ]; then HISTFILE=$_hv; else unset HISTFILE; fi
unset _xt _hf _hv
