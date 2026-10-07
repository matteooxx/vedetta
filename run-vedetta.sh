#!/bin/sh
# Daily Vedetta run, and delivery of whatever it queued.
#
# Lives in the dataset on tank, not in /root: every other application's cron script on
# this box sits on the single-disk boot pool, which is near end of life, is not
# snapshotted and is not backed up. This one is covered by the dataset's daily
# snapshot like the rest of the application. Its log goes to the dataset for the same
# reason.
#
# The application has no mail credential of its own. It writes the digest to an
# outbox; this script delivers it with the machine's own mail configuration, which is
# already set up and already works. Nothing to create, nothing to rotate, nothing to
# leak — and an undelivered digest stays queued and is retried rather than lost.
set -eu

ROOT=/srv/vedetta
IMAGE=vedetta:local
LOG="$ROOT/logs/vedetta.log"
ENVFILE="$ROOT/runtime/app.env"
OUTBOX="$ROOT/runtime/outbox"

mkdir -p "$ROOT/logs"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

# Run the application in a throwaway container with the same hardening the long-running
# interface uses.
vedetta() {
  docker run --rm \
    --user 1000:1000 \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --memory 512m --cpus 2 --pids-limit 128 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
    -v "$ROOT/runtime:/data/runtime:rw" \
    -v "$ROOT/config:/data/config:ro" \
    "$IMAGE" "$@"
}

log "run starting"

# A fixed container name is worth having, for `docker logs`. But --rm only fires on a
# clean exit, so a container can be left behind and then the name collides: every later
# run dies with exit 125 and the watch stops without anyone noticing, which is this
# project's cardinal sin.
#
# The distinction matters, and getting it wrong once nearly destroyed an hour of work:
# a container with that name may be a corpse OR a run still going. The shell session
# that launched it can be gone while the container keeps working, so a missing lock
# file is not proof that nothing is running. Only a dead one is removed.
RUNNING=$(docker ps --filter name=vedetta-run --format '{{.Names}}' 2>/dev/null || true)
if [ -n "$RUNNING" ]; then
  log "another run is still in progress (container vedetta-run is up); leaving it alone"
  exit 0
fi
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'vedetta-run'; then
  log "removing an exited vedetta-run container left behind by an interrupted run"
  docker rm vedetta-run >/dev/null 2>&1 || true
fi

set +e
OUTPUT=$(docker run --rm --name vedetta-run \
  --user 1000:1000 --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --memory 512m --cpus 2 --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  -v "$ROOT/runtime:/data/runtime:rw" \
  -v "$ROOT/config:/data/config:ro" \
  "$IMAGE" run --trigger schedule 2>&1)
STATUS=$?
set -e

printf '%s\n' "$OUTPUT" >> "$LOG"

if [ "$STATUS" -ne 0 ]; then
  log "run FAILED with exit status $STATUS"
  if command -v midclt >/dev/null 2>&1; then
    printf '%s' "$OUTPUT" | tail -30 | python3 -c '
import json, subprocess, sys
body = sys.stdin.read()
subprocess.run(["midclt", "call", "mail.send", json.dumps({
    "subject": "Vedetta run failed",
    "text": "The daily run exited with a failure. Last lines:\n\n" + body,
})], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
' || true
  fi
  exit "$STATUS"
fi

# ---------------------------------------------------------------------- delivery
#
# Anything the run queued, plus anything an earlier run failed to deliver. Retrying is
# the whole reason the outbox exists: an unsent digest is the one failure the reader
# cannot discover by reading the digest.
DELIVERED=0
FAILED=0
for FILE in "$OUTBOX"/run-*.txt; do
  [ -e "$FILE" ] || break
  RUN_ID=$(basename "$FILE" .txt | sed 's/^run-//')
  RECIPIENT=$(sed -n 's/^VEDETTA_MAIL_TO=//p' "$ENVFILE" 2>/dev/null | head -1)

  if python3 - "$FILE" "$RECIPIENT" <<'PY'
import json, subprocess, sys
path, recipient = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "").strip()
text = open(path, encoding="utf-8").read()
subject, _, body = text.partition("\n\n")
payload = {"subject": subject.strip() or "Vedetta digest", "text": body}
if recipient:
    payload["to"] = [recipient]
# Built in Python rather than quoted through the shell: the digest is multi-line and
# quoting one of those into midclt is a documented way to lose an evening.
subprocess.run(["midclt", "call", "mail.send", json.dumps(payload)], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
PY
  then
    # Recorded in the database by the application itself, so "was it sent?" has one
    # answer rather than two that can disagree.
    if vedetta outbox --sent "$RUN_ID" >/dev/null 2>&1; then
      log "digest for run $RUN_ID delivered through the host mail transport"
      DELIVERED=$((DELIVERED + 1))
    else
      log "digest for run $RUN_ID was sent but could not be recorded; it stays queued"
      FAILED=$((FAILED + 1))
    fi
  else
    log "digest for run $RUN_ID could not be sent; left queued for the next run"
    FAILED=$((FAILED + 1))
  fi
done

if [ "$FAILED" -gt 0 ]; then
  log "run finished with $DELIVERED delivered and $FAILED still queued"
  exit 1
fi

log "run finished cleanly ($DELIVERED digest(s) delivered)"
