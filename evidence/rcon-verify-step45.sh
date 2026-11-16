#!/bin/bash
# RCON rotation, steps 4-5: verify the restart regenerated holders 3/4, and the
# full four-check verification. Prints fingerprints and lengths ONLY.
# Per lead 15:26Z: no ad-hoc inspection of secret values; fingerprints come from
# sha256 only, never from sed/cut output.
set -eu
NS=minecraft-test
POD=$(kubectl -n "$NS" get pod -l app=minecraft-test-server \
      -o jsonpath='{.items[0].metadata.name}')
POD_START=$(kubectl -n "$NS" get pod "$POD" -o jsonpath='{.status.startTime}')

echo "pod=$POD"
echo "pod_start=$POD_START"

# ---- step 4: holders 3 and 4 are DERIVED; verify regeneration, do not edit ----
for f in /data/.rcon-cli.env /data/.rcon-cli.yaml; do
  mtime=$(kubectl -n "$NS" exec "$POD" -c mc-server -- stat -c %Y "$f" 2>/dev/null || echo 0)
  start_epoch=$(date -d "$POD_START" +%s)
  if [ "$mtime" -gt "$start_epoch" ]; then fresher=newer; else fresher=STALE; fi
  echo "derived $f mtime_fresher_than_start=$fresher"
done

# ---- fingerprints of all four holders, sha256 only ----
# EMPTY_256 is the sha256 of "" -- if any extraction yields it, the extraction
# found nothing and the hash is meaningless, not a match. Fail loudly instead.
EMPTY_256=e3b0c44298fc1c14
check_not_empty() {
  if [ "$2" = "$EMPTY_256" ]; then
    echo "EXTRACT_FAILED $1 produced the empty-string hash -- grep found nothing"
    return 1
  fi
}

# Secret
SEC_FP=$(kubectl -n "$NS" get secret minecraft-rcon -o jsonpath='{.data.password}' \
         | base64 -d | sha256sum | cut -c1-16)
check_not_empty secret "$SEC_FP"
echo "fp_secret=$SEC_FP"

# Holder 2: server.properties -- take everything after the FIRST '=' only.
PROP_FP=$(kubectl -n "$NS" exec "$POD" -c mc-server -- \
  sh -c 'grep "^rcon\.password=" /data/server.properties | head -1 | cut -d= -f2-' \
  | tr -d '\r\n' | sha256sum | cut -c1-16)
check_not_empty server_properties "$PROP_FP"
echo "fp_server_properties=$PROP_FP"

# Holder 3: dotenv
ENV_FP=$(kubectl -n "$NS" exec "$POD" -c mc-server -- \
  sh -c 'grep "^password=" /data/.rcon-cli.env | head -1 | cut -d= -f2-' \
  | tr -d '\r\n' | sha256sum | cut -c1-16)
check_not_empty dotenv "$ENV_FP"
echo "fp_dotenv=$ENV_FP"

# Holder 4: yaml, double-quoted -- strip the quotes, which are the format not the value
YML_FP=$(kubectl -n "$NS" exec "$POD" -c mc-server -- \
  sh -c 'grep "^password:" /data/.rcon-cli.yaml | head -1 | cut -d: -f2-' \
  | tr -d ' \r\n"' | sha256sum | cut -c1-16)
check_not_empty yaml "$YML_FP"
echo "fp_yaml=$YML_FP"

if [ "$SEC_FP" = "$PROP_FP" ] && [ "$SEC_FP" = "$ENV_FP" ] && [ "$SEC_FP" = "$YML_FP" ]; then
  echo "all_four_match=yes"
else
  echo "all_four_match=NO"
fi

# new value length, from the Secret
LEN=$(kubectl -n "$NS" get secret minecraft-rcon -o jsonpath='{.data.password}' \
      | base64 -d | wc -c)
echo "new_len=$LEN"

# ---- 5(a): rcon with the NEW value answers a real command ----
echo "--- 5a ---"
kubectl -n "$NS" exec "$POD" -c mc-server -- sh -c 'HOME=/data rcon-cli list' 2>&1 \
  | grep -oE 'There are [0-9]+ of a max of [0-9]+ players online' | head -1 \
  || echo "5a_FAILED_no_reply"
