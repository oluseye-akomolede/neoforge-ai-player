#!/usr/bin/env bash
# Enumerate every rcon password ASSIGNMENT on the TEST data volume and report
# what each one carries, WITHOUT searching for a particular value.
#
# Why this shape: the prescribed 5(c) greps for the old value, which needs that
# value to survive from step 1 to step 5. In the real run it did not (compaction
# separated them), and a value-search can only find holders inside a set you
# already believe complete -- which is how section 1's scan missed the two
# dotfiles. This scan instead enumerates the assignments and inspects each one,
# so a holder nobody listed still appears in the output.
#
# It never prints a value: only a fingerprint per holder, secret included.
# The value is handed to the pod on STDIN, never in argv and never in a file.
#
# Run:  bash evidence/rcon-enumerate-scan.sh

set -u
NS=minecraft-test
DEPLOY=minecraft-test-server          # whose /data volume this is
CTR=mc-server
# Selector DERIVED from the deployment, not guessed: an earlier version
# hard-coded app=aibot-agent and silently targeted the AGENT pod, which has no
# /data and no rcon password. The positive control caught it (0 files, refused).
SEL=$(ssh controlplane "kubectl -n $NS get deploy $DEPLOY -o jsonpath='{.spec.selector.matchLabels.app}'")
[ -n "$SEL" ] || { echo "REFUSED: cannot read $DEPLOY selector" >&2; exit 2; }
POD=$(ssh controlplane "kubectl -n $NS get pods -l app=$SEL -o jsonpath='{.items[0].metadata.name}'")
[ -n "$POD" ] || { echo "REFUSED: no pod for app=$SEL" >&2; exit 2; }
echo "pod=$POD  selector=app=$SEL  container=$CTR"

# The scan. It takes the value from the environment ($NEW, exported by the
# wrapper) rather than from stdin, because sh executes stdin as commands -- the
# first version piped the value there and sh ran it ("e378fde9...: not found"),
# leaving NEW empty and making an empty grep pattern match every file. The
# 48-char gate below is what turns that failure into a refusal instead of a
# 20-file "success".
read -r -d '' SCAN <<'EOS'
NEW=${NEW:-}
# NO FINGERPRINT IS PRINTED. A 16-hex digest of a live credential is a cheap
# way to check a guess, and this script's output gets pasted into plans. The
# length and the counts below establish everything the rotation needs.
echo "new_len=${#NEW}"
if [ "${#NEW}" -ne 48 ]; then
  echo "REFUSED: value is ${#NEW} chars, expected 48 -- scan would be meaningless" >&2
  exit 3
fi
echo "--- S2: rcon-password ASSIGNMENTS (key names only, never values) ---"
# Classify by the VALUE a bare `password=` carries, NOT by whether the file
# mentions the string "rcon". The first version did the latter and classed the
# two .rcon-cli files as OTHER -- so the final "every rcon assignment carries
# the new value" passed while two of the three real holders sat outside the
# checked set. A green check that excludes the files that already bit us.
#   RCON  -- key is rcon.password, OR a bare password= that holds the secret
#   OTHER -- a password field holding something else (AE2 mod, Showdown JS)
# A third class, UNKNOWN, is the fix for the hole a reviewer found: a bare
# password= holding a STALE rcon value used to land in OTHER and never be
# checked, so the final gate passed with an unlisted holder present. Now a
# password field is only OTHER if the file is one of the KNOWN non-rcon files;
# anything else is UNKNOWN, which fails the run.
#
# The allowlist is by PATH, deliberately not by value fingerprint. A fingerprint
# allowlist would need the AE2 credential's digest committed here, which is the
# same oracle-by-digest mistake this rotation exists to stop making -- and a
# stale rcon value would be invisible only if it hashed to the AE2 value.
KNOWN_OTHER_PATHS='/data/config/ae2webintegration.toml
/data/config/pokemon-showdown/config/replays.js'
find /data -type f -size -64k 2>/dev/null | while read -r f; do
  if grep -qE "^[[:space:]]*rcon\.password[[:space:]]*[=:]" "$f" 2>/dev/null; then
    echo "RCON $f"
  elif grep -qE "^[[:space:]]*password[[:space:]]*[=:]" "$f" 2>/dev/null; then
    if grep -qF -- "$NEW" "$f" 2>/dev/null; then
      echo "RCON $f"
    elif printf '%s\n' "$KNOWN_OTHER_PATHS" | grep -qxF -- "$f"; then
      echo "OTHER $f"
    else
      echo "UNKNOWN $f"
    fi
  fi
done
echo "--- S1: files CONTAINING the current value ---"
find /data -type f -size -64k 2>/dev/null | while read -r f; do
  grep -qF -- "$NEW" "$f" 2>/dev/null && echo "HAS_NEW $f"
done
echo "--- END ---"
EOS

# Delivery, after three wrong attempts at keeping the value off one stream.
# The working shape: the remote shell reads the value from stdin (fd 0) into a
# variable, then runs the script (which arrives base64'd in the command) with
# that variable EXPORTED to it. Nothing is written to a file on either host,
# the value is not in any argv, and it is exported only into the scan process.
VAL=$(ssh controlplane "kubectl -n $NS get secret minecraft-rcon -o jsonpath='{.data.password}'" | base64 -d | tr -d '\n')
[ "${#VAL}" -eq 48 ] || { echo "REFUSED: secret decoded to ${#VAL} chars, expected 48" >&2; exit 3; }
SCAN_B64=$(printf '%s' "$SCAN" | base64 -w0)
# Read the value on the CONTROLPLANE shell's stdin, then exec into the pod with
# it as an env var. $1 carries the base64 script; the value never appears in it.
OUT=$(printf '%s\n' "$VAL" | ssh controlplane "IFS= read -r V; printf '%s' \"\$V\" | kubectl -n $NS exec -i $POD -c $CTR -- sh -c 'read -r NEW; export NEW; echo $SCAN_B64 | base64 -d | sh'")
unset VAL SCAN_B64
echo "$OUT"

echo
echo "=== controls ==="
judge_scan() {
OUT="$1"
# Gate 0: the scanner must have had a 48-char needle. An empty NEW makes grep
# match every file, which reads as a huge success -- this is the check that
# would have caught the first run.
NEWLEN=$(echo "$OUT" | sed -n 's/^new_len=//p')
echo "needle_length=$NEWLEN (must be 48)"
if [ "$NEWLEN" != "48" ]; then
  echo "SCAN INVALID: the scanner had no usable needle; every count below is noise" >&2
  exit 1
fi
hasnew=$(echo "$OUT" | grep -c '^HAS_NEW')
assigned=$(echo "$OUT" | grep -c '^RCON')
other=$(echo "$OUT" | grep -c '^OTHER')
unknown=$(echo "$OUT" | grep -c '^UNKNOWN')
echo "positive control: files containing the new value = $hasnew (expect 3)"
echo "rcon_assignments=$assigned   holding_new_value=$hasnew   non_rcon_password_fields=$other   unknown_password_fields=$unknown"
if [ "$hasnew" -lt 3 ]; then
  echo "POSITIVE CONTROL FAILED: scanner is blind, its zero means nothing" >&2
  exit 1
fi
# An UNKNOWN is a password= that is neither the new value nor a known non-rcon
# file. That is precisely the "holder nobody listed" the enumerate form exists
# to surface, so it fails rather than being printed and passed over.
if [ "$unknown" -gt 0 ]; then
  echo "UNKNOWN PASSWORD FIELD(S) -- neither the new value nor a known non-rcon file:" >&2
  echo "$OUT" | grep '^UNKNOWN' >&2
  exit 1
fi
# Set comparison, not a count comparison: every RCON assignment must ALSO be in
# the set holding the new value. A count test passes if one assignment and one
# unrelated consumer are both present.
echo "$OUT" | grep '^RCON' | awk '{print $2}' | sort > /tmp/.assign_set
echo "$OUT" | grep '^HAS_NEW' | awk '{print $2}' | sort > /tmp/.hasnew_set
UNCOVERED=$(comm -23 /tmp/.assign_set /tmp/.hasnew_set)
rm -f /tmp/.assign_set /tmp/.hasnew_set
if [ -n "$UNCOVERED" ]; then
  echo "UNCOVERED HOLDER(S) -- these assign an rcon password that is not the new value:" >&2
  echo "$UNCOVERED" >&2
  exit 1
fi
}
# The decision is a function so it can be driven from a fixture (see
# evidence/rcon-scan-selftest.sh). A gate that only exists inline is a gate
# nobody can demonstrate failing, which is how the OTHER hole survived review.
judge_scan "$OUT"
echo "OK: every rcon assignment on the volume carries the new value"
