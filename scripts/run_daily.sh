#!/usr/bin/env bash
# AI Radar — Daily orchestrator
# Triggered by launchd at 07:07 AM daily.
# Runs the OpenClaw/OpenRouter Python pipeline so Claude Code quota does not
# affect daily delivery.

set -euo pipefail

RADAR_DIR="$HOME/ai-radar"
OUTPUT_DIR="$RADAR_DIR/output"
LOG_DIR="$RADAR_DIR/logs"
TODAY=$(date +%Y-%m-%d)
HTML_OUTPUT="$RADAR_DIR/docs/$TODAY.html"
HTML_OUTPUT_EN="$RADAR_DIR/docs/en/$TODAY.html"
LOG_FILE="$LOG_DIR/daily-$TODAY.log"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"

# launchd can miss StartCalendarInterval while the Mac is asleep. This script
# is also run hourly as a catch-up check; skip before the normal morning window
# and skip if today's published digest already exists.
if [[ $# -eq 0 ]]; then
  HOUR=$(date +%H)
  if [[ "$HOUR" -lt 7 ]]; then
    echo "[$(date)] Before 07:00; skipping catch-up check." | tee -a "$LOG_FILE"
    exit 0
  fi

  if [[ -f "$HTML_OUTPUT" && -f "$HTML_OUTPUT_EN" ]]; then
    echo "[$(date)] Today's digest already exists in both languages; skipping." | tee -a "$LOG_FILE"
    exit 0
  fi
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found in PATH" | tee -a "$LOG_FILE"
  exit 1
fi

echo "[$(date)] Running daily digest via OpenRouter/OpenClaw..." | tee -a "$LOG_FILE"
python3 "$RADAR_DIR/scripts/run_daily.py" "$@" 2>&1 | tee -a "$LOG_FILE"
echo "[$(date)] Daily run complete." | tee -a "$LOG_FILE"
