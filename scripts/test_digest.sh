#!/usr/bin/env bash
# AI Radar — Manual test script
# Runs the daily digest and prints to stdout instead of pushing.
# Use this to validate format changes before they go live.

set -euo pipefail

RADAR_DIR="$HOME/ai-radar"
PROMPT_FILE="$RADAR_DIR/prompts/digest.md"
TEST_OUTPUT="/tmp/ai-radar-test-$(date +%s).md"

echo "🧪 Running test digest (no Discord/email push)..."
echo "    Output will be: $TEST_OUTPUT"
echo ""

claude -p "Execute the AI Radar daily digest. Read the system prompt from $PROMPT_FILE. Fetch sources. Write the formatted digest to $TEST_OUTPUT." \
  --allowedTools WebFetch,Write,Read,Bash

echo ""
echo "=========================================="
echo "Test digest output:"
echo "=========================================="
cat "$TEST_OUTPUT"
echo ""
echo "=========================================="
echo "📁 Saved to: $TEST_OUTPUT"
