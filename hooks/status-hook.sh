#!/bin/bash
# Claude Code hook: write agent state for WezTerm sidebar.
# Usage: claude-status-hook.sh <state> [force]
# States: working, waiting, idle, cleanup, subagent-start, subagent-stop
#
# Writes /tmp/wezterm-hook-<pane_id>.json so the sidebar can read it.
# Only writes if WEZTERM_PANE is set (= running inside WezTerm).
#
# Subagent tracking: SubagentStart/SubagentStop maintain a counter at
# /tmp/wezterm-sa-<pane_id>. When subagents are active AND state is
# "waiting", PostToolUse's "working" is blocked (sticky guard).
# When no subagents are active, PostToolUse always writes freely.

STATE="${1:-idle}"
FORCE="${2:-}"
PANE_ID="${WEZTERM_PANE:-}"

# Silently exit if not in WezTerm
[ -z "$PANE_ID" ] && exit 0

STATUS_FILE="/tmp/wezterm-hook-${PANE_ID}.json"
SA_COUNT_FILE="/tmp/wezterm-sa-${PANE_ID}"

# --- Subagent counter management ---
if [ "$STATE" = "subagent-start" ]; then
    flock "$SA_COUNT_FILE" bash -c \
        'echo $(( $(cat "$1" 2>/dev/null || echo 0) + 1 )) > "$1"' -- "$SA_COUNT_FILE"
    exit 0
fi

if [ "$STATE" = "subagent-stop" ]; then
    flock "$SA_COUNT_FILE" bash -c \
        'n=$(cat "$1" 2>/dev/null || echo 1); echo $(( n > 0 ? n - 1 : 0 )) > "$1"' -- "$SA_COUNT_FILE"
    exit 0
fi

# --- Status file management ---
if [ "$STATE" = "cleanup" ]; then
    rm -f "$STATUS_FILE" "$SA_COUNT_FILE"
    exit 0
fi

# Sticky guard: "working" (without force) cannot overwrite "waiting"
# when subagents are active. This prevents subagent PostToolUse from
# clobbering PermissionRequest's state, while allowing the main agent's
# PostToolUse to clear "waiting" after permission is granted (when
# subagents have finished).
if [ "$STATE" = "working" ] && [ "$FORCE" != "force" ] && [ -f "$STATUS_FILE" ]; then
    CURRENT=$(grep -o '"status":"[^"]*"' "$STATUS_FILE" 2>/dev/null | head -1 | cut -d'"' -f4)
    if [ "$CURRENT" = "waiting" ]; then
        SA_COUNT=$(cat "$SA_COUNT_FILE" 2>/dev/null || echo 0)
        if [ "$SA_COUNT" -gt 0 ]; then
            exit 0
        fi
    fi
fi

TMP="${STATUS_FILE}.tmp"
printf '{"status":"%s","ts":%d}\n' "$STATE" "$(date +%s)" > "$TMP"
mv "$TMP" "$STATUS_FILE"

exit 0
