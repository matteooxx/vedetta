#!/bin/sh
# Daily Vedetta run, and delivery of whatever it queued.
#
# Install this wherever the application's data lives, rather than in a home directory
# or /root. On the machine it was written for that meant a snapshotted dataset on the
# storage pool instead of the single-disk boot pool, which is neither snapshotted nor
# backed up. The log goes next to the data for the same reason.
#
# The application has no mail credential of its own. It writes the digest to an
# outbox; this script delivers it with the machine's own mail configuration, which is
# already set up and already works. Nothing to create, nothing to rotate, nothing to
# leak — and an undelivered digest stays queued and is retried rather than lost.
set -eu

# The directory holding `runtime/`, `config/` and `logs/`. It defaults to this
# script's own directory, so a clone works where it stands; set VEDETTA_ROOT when the
# script lives apart from the data it manages.
ROOT="${VEDETTA_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
IMAGE="${VEDETTA_IMAGE:-vedetta:local}"
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

  # Delivery goes through a script using the middleware client, not through midclt
  # with a quoted argument. The first version did the latter and failed with
  # "sudo: argv[3] mismatch" on a 15 KB payload - which is the handbook's own warning
  # (api.md F-1, F-2) arriving on schedule. Its stderr is kept, not discarded: the
  # first version hid the reason it failed, in a project whose whole point is that
  # failures are visible.
  if DELIVERY=$(python3 "$ROOT/deliver-digest.py" "$FILE" "$RECIPIENT" 2>&1); then
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
    log "  reason: $DELIVERY"
    FAILED=$((FAILED + 1))
  fi
done

if [ "$FAILED" -gt 0 ]; then
  log "run finished with $DELIVERED delivered and $FAILED still queued"
  exit 1
fi

log "run finished cleanly ($DELIVERED digest(s) delivered)"
