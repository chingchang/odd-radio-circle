#!/bin/bash
# Runs plan items from a queue so nobody has to type the next command. Start it once, in the worktree, and
# leave it running:
#
#   cd ~/finding-landers/.claude/worktrees/repo-overview-plan-e248f3
#   caffeinate -i scripts/autopilot.sh
#
# Every minute it looks at out/queue/next. If the file holds an item id (one line, e.g. "8" or "9b"), it
# removes the file and runs that item through scripts/run_plan.sh with the caps below, then waits for the
# next entry. A file out/queue/STOP ends it after the current item. A second autopilot in the same worktree
# is refused (two agents in one tree collide). Who writes the queue: a person, or the oracle through the
# shared folder; the item still runs under the same plan, guards and caps as a hand-started one.
set -uo pipefail
cd "$(dirname "$0")/.."
Q=out/queue; mkdir -p "$Q"
LOCK="$Q/autopilot.pid"
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then echo "an autopilot is already running here (pid $(cat "$LOCK"))"; exit 1; fi
echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT
ITEM_USD="${ITEM_USD:-30}"; ITEM_TURNS="${ITEM_TURNS:-400}"; export ITEM_USD ITEM_TURNS
echo "autopilot up in $(pwd); queue is $Q/next"
while true; do
  if [ -f "$Q/STOP" ]; then echo "STOP found; leaving"; rm -f "$Q/STOP"; exit 0; fi
  if [ -f "$Q/next" ]; then
    item="$(head -1 "$Q/next" | tr -d '[:space:]')"; rm -f "$Q/next"
    if [ -n "$item" ]; then
      echo "== $(date '+%F %T') running item $item"
      # The paid item (the person allowed this, 10-31 10:38): load the key from the person's own env file, for this
      # item only, so no one has to be at the keyboard. The probes' ledger caps the run at 10 USD.
      if [ "$item" = "5" ] && [ -f "$HOME/.config/finding-landers/env" ]; then
        ( set -a; . "$HOME/.config/finding-landers/env"; set +a; export LANDERS_REAL_CALLS=1
          ITEM="$item" scripts/run_plan.sh >> "$Q/autopilot.log" 2>&1 )
      else
        ITEM="$item" scripts/run_plan.sh >> "$Q/autopilot.log" 2>&1
      fi
      echo "== $(date '+%F %T') item $item finished with exit $?"
      git merge --no-edit main >/dev/null 2>&1 || true
    fi
  fi
  sleep 60
done
