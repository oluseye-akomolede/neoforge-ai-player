#!/usr/bin/env bash
# Drives the REAL decision function from rcon-enumerate-scan.sh against fixture
# scan output, so the gate can be shown to fail instead of merely being read.
#
# Why this exists: a reviewer found that a bare `password=` holding a stale
# value was classified OTHER, printed, and never checked -- so the final "every
# rcon assignment carries the new value" passed with an unlisted holder
# present. The classification was fixed, but a fix to classification is worth
# nothing unless the DECISION reaches it. The first version of this self-test
# proved the hole was still open: UNKNOWN was printed and RC was 0, because the
# gate lived in a code path the fixture never ran.
#
# Run:  bash evidence/rcon-scan-selftest.sh        (no cluster, no secret)

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/rcon-enumerate-scan.sh"

# Extract judge_scan from the real script rather than copying it. A copy would
# agree with itself and prove nothing.
FUNC=$(sed -n '/^judge_scan() {/,/^}$/p' "$SRC")
[ -n "$FUNC" ] || { echo "FAIL: could not extract judge_scan from $SRC" >&2; exit 1; }
eval "$FUNC"

fail=0
expect() {  # expect <label> <want-rc> <output>
  local label="$1" want="$2" out="$3" rc
  ( judge_scan "$out" ) >/dev/null 2>&1
  rc=$?
  if [ "$rc" -eq "$want" ]; then
    echo "PASS  $label (rc=$rc)"
  else
    echo "FAIL  $label: expected rc=$want, got rc=$rc" >&2
    fail=1
  fi
}

good='new_len=48
--- S2 ---
RCON /data/.rcon-cli.env
RCON /data/server.properties
OTHER /data/config/ae2webintegration.toml
RCON /data/.rcon-cli.yaml
--- S1 ---
HAS_NEW /data/.rcon-cli.env
HAS_NEW /data/server.properties
HAS_NEW /data/.rcon-cli.yaml
--- END ---'

stale='new_len=48
--- S2 ---
RCON /data/.rcon-cli.env
RCON /data/server.properties
OTHER /data/config/ae2webintegration.toml
UNKNOWN /data/config/some-new-mod.conf
RCON /data/.rcon-cli.yaml
--- S1 ---
HAS_NEW /data/.rcon-cli.env
HAS_NEW /data/server.properties
HAS_NEW /data/.rcon-cli.yaml
--- END ---'

# The realistic empty-needle hazard: an empty pattern makes `grep -F` match
# EVERY file, so S1 reports more hits than there are holders -- every count
# control passes. Only the needle-length gate can reject this.
#
# The first version of this fixture had a single HAS_NEW line, so with the gate
# disabled it still failed via `hasnew < 3`. It asserted rc=1 and passed without
# ever reaching the gate it names -- the fixture confirming the consumer again.
empty_needle='new_len=0
--- S2 ---
RCON /data/.rcon-cli.env
RCON /data/server.properties
RCON /data/.rcon-cli.yaml
--- S1 ---
HAS_NEW /data/.rcon-cli.env
HAS_NEW /data/server.properties
HAS_NEW /data/.rcon-cli.yaml
HAS_NEW /data/README.txt
HAS_NEW /data/banned-ips.json
--- END ---'

blind='new_len=48
--- S1 ---
HAS_NEW /data/only-one
--- END ---'

uncovered='new_len=48
--- S2 ---
RCON /data/server.properties
RCON /data/a-second-holder
--- S1 ---
HAS_NEW /data/server.properties
HAS_NEW /data/.rcon-cli.env
HAS_NEW /data/.rcon-cli.yaml
--- END ---'

expect "three correct holders, known non-rcon file"        0 "$good"
expect "unlisted holder with a stale value must FAIL"      1 "$stale"
expect "empty needle must FAIL, not match everything"      1 "$empty_needle"
expect "blind scanner (1 file) must FAIL its control"      1 "$blind"
expect "a listed holder without the new value must FAIL"   1 "$uncovered"

if [ "$fail" -ne 0 ]; then
  echo "SELF-TEST FAILED" >&2
  exit 1
fi
echo "SELF-TEST OK: the gate fails on every bad state it exists for"
