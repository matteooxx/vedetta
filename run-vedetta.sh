#!/bin/sh
# Daily Vedetta run. Invoked by a TrueNAS cron job.
#
# Lives in the dataset on tank, not in /root: every other application's cron script
# on this box sits on the single-disk boot pool, which is near end of life, is not
# snapshotted and is not backed up. This one is covered by the dataset's daily
# snapshot like the rest of the application.
#
# Logs go to the dataset for the same reason.
set -eu

ROOT=/srv/vedetta
IMAGE=vedetta:local
LOG="$ROOT/logs/vedetta.log"
ENVFILE="$ROOT/runtime/app.env"

mkdir -p "$ROOT/logs"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

log "run starting"

# The image carries no secrets; the env file supplies the mailbox credentials.
ENV_ARG=""
if [ -f "$ENVFILE" ]; then
  ENV_ARG="--env-file $ENVFILE"
else
  log "WARNING: $ENVFILE is missing - the digest will print instead of sending"
fi

# A fixed container name is worth having, for `docker logs`. But --rm only fires on a
# clean exit, so a container can be left behind and then the name collides: every
# later run dies with exit 125 and the watch stops without anyone noticing, which is
# this project's cardinal sin.
#
# The distinction matters, and getting it wrong once nearly destroyed an hour of
# work: a container with that name may be a corpse OR a run still going. The shell
# session that launched it can be gone while the container keeps working, so a
# missing lock file is not proof that nothing is running. Only a dead one is removed.
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
# shellcheck disable=SC2086
OUTPUT=$(docker run --rm \
  --name vedetta-run \
  --user 1000:1000 \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --memory 512m --cpus 2 --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  -v "$ROOT/runtime:/data/runtime:rw" \
  -v "$ROOT/config:/data/config:ro" \
  $ENV_ARG \
  "$IMAGE" run --trigger schedule 2>&1)
STATUS=$?
set -e

printf '%s\n' "$OUTPUT" >> "$LOG"

# Exit 2 means the application could not send the digest itself, because no SMTP
# password is configured. The digest still exists - it was printed - and the server's
# own mail transport is already configured and working, so it goes out that way
# instead. This is a fallback, not the design: once an app password is in app.env the
# application sends directly and this branch never runs.
#
# It is worth having because an unsent digest is the one failure the operator cannot
# discover by reading the digest.
if [ "$STATUS" -eq 2 ]; then
  RECIPIENT=$(sed -n 's/^VEDETTA_MAIL_TO=//p' "$ENVFILE" 2>/dev/null | head -1)
  if [ -n "$RECIPIENT" ] && command -v midclt >/dev/null 2>&1; then
    SUBJECT=$(printf '%s' "$OUTPUT" | sed -n 's/^Vedetta: //p' | head -1)
    [ -n "$SUBJECT" ] || SUBJECT="daily digest"
    # Build the payload in Python rather than in the shell: the digest is multi-line
    # and quoting it through zsh into midclt is a documented way to lose an evening.
    printf '%s' "$OUTPUT" | python3 -c '
import json, subprocess, sys
recipient, subject = sys.argv[1], sys.argv[2]
body = sys.stdin.read()
payload = json.dumps({"subject": subject, "text": body, "to": [recipient]})
subprocess.run(["midclt", "call", "mail.send", payload], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
' "$RECIPIENT" "Vedetta: $SUBJECT" && {
      log "digest sent to $RECIPIENT through the server mail transport (no app password set)"
      log "run finished cleanly"
      exit 0
    }
    log "fallback mail transport ALSO failed - the digest is in this log only"
  fi
fi

if [ "$STATUS" -ne 0 ]; then
  log "run FAILED with exit status $STATUS"
  # A failure to send is the one fault the operator cannot discover by reading the
  # digest, so it is escalated by a separate channel.
  if command -v midclt >/dev/null 2>&1; then
    midclt call mail.send "{\"subject\":\"Vedetta run failed (exit $STATUS)\",\"text\":\"The daily Vedetta run exited with status $STATUS. Last lines:\n\n$(printf '%s' "$OUTPUT" | tail -20)\"}" >/dev/null 2>&1 || true
  fi
  exit "$STATUS"
fi

log "run finished cleanly"
