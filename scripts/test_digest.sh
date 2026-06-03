#!/usr/bin/env bash
# AI Radar — Manual test script
# Runs the daily digest through OpenRouter and skips git/Discord.
# Use this to validate format changes before they go live.

set -euo pipefail

RADAR_DIR="$HOME/ai-radar"

echo "Running test digest (no git, no Discord)..."
python3 "$RADAR_DIR/scripts/run_daily.py" --test --no-git --no-discord "$@"
