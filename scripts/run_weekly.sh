#!/usr/bin/env bash
# AI Radar — Weekly orchestrator
# Triggered by launchd Sunday 08:00 AM.
# Runs the OpenClaw/OpenRouter Python pipeline; no Claude Code CLI dependency.

set -euo pipefail

RADAR_DIR="$HOME/ai-radar"
LOG_DIR="$RADAR_DIR/logs"
TODAY=$(date +%Y-%m-%d)
OUTPUT_FILE="$RADAR_DIR/docs/weekly_$TODAY.html"
OUTPUT_FILE_EN="$RADAR_DIR/docs/en/weekly_$TODAY.html"
LOG_FILE="$LOG_DIR/weekly-$TODAY.log"

mkdir -p "$LOG_DIR"

if [[ $# -eq 0 && -f "$OUTPUT_FILE" && -f "$OUTPUT_FILE_EN" ]]; then
  echo "[$(date)] This week's wrap already exists in both languages; skipping." | tee -a "$LOG_FILE"
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found in PATH" | tee -a "$LOG_FILE"
  exit 1
fi

echo "[$(date)] Running weekly wrap via OpenRouter/OpenClaw..." | tee -a "$LOG_FILE"
python3 "$RADAR_DIR/scripts/run_weekly.py" "$@" 2>&1 | tee -a "$LOG_FILE"
echo "[$(date)] Weekly run complete." | tee -a "$LOG_FILE"
