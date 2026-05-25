#!/usr/bin/env bash
# AI Radar — Daily orchestrator
# Triggered by launchd at 07:07 AM daily.
# Runs claude with the digest prompt — claude itself fetches sources,
# writes the output file, and pushes to Discord via the MCP reply tool.

set -euo pipefail

RADAR_DIR="$HOME/ai-radar"
PROMPT_FILE="$RADAR_DIR/prompts/digest.md"
OUTPUT_DIR="$RADAR_DIR/output"
LOG_DIR="$RADAR_DIR/logs"
TODAY=$(date +%Y-%m-%d)
OUTPUT_FILE="$OUTPUT_DIR/$TODAY.md"
LOG_FILE="$LOG_DIR/daily-$TODAY.log"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"

# Optional config (only email needs config — Discord uses MCP directly)
CONFIG_FILE="$RADAR_DIR/.config.env"
if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

EMAIL_TO="${AIRADAR_EMAIL_TO:-jim.liumingjing@gmail.com}"
EMAIL_FROM="${AIRADAR_EMAIL_FROM:-}"
GMAIL_APP_PASSWORD="${AIRADAR_GMAIL_APP_PASSWORD:-}"

echo "[$(date)] Running daily digest..." | tee -a "$LOG_FILE"

if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: claude CLI not found in PATH" | tee -a "$LOG_FILE"
  exit 1
fi

# Claude executes the full pipeline: fetch sources, write output file,
# push to Discord via MCP reply tool. The prompt specifies exact channel ID.
HTML_OUTPUT="$HOME/ai-radar/docs/$TODAY.html"

claude -p "Execute the AI Radar daily digest workflow per the system prompt at $PROMPT_FILE. Today is $TODAY. Follow ALL 5 phases: (1) fetch sources, (2) filter+rank, (3) write HTML to $HTML_OUTPUT + $HOME/ai-radar/docs/index.html + $OUTPUT_FILE markdown copy, (4) git add+commit+push from $HOME/ai-radar, (5) wait for Pages then Discord push to chat_id 1484904539952775351 with $HTML_OUTPUT attached and the URL https://ethan-m25.github.io/ai-radar/" \
  --allowedTools "WebFetch,Write,Read,Bash,mcp__plugin_discord_discord__reply" \
  2>&1 | tee -a "$LOG_FILE"

if [[ ! -f "$HTML_OUTPUT" ]]; then
  echo "ERROR: HTML digest was not created at $HTML_OUTPUT" | tee -a "$LOG_FILE"
  exit 1
fi

echo "[$(date)] Digest + Discord push complete." | tee -a "$LOG_FILE"

# Optional email copy
if [[ -n "$EMAIL_FROM" && -n "$GMAIL_APP_PASSWORD" ]]; then
  echo "[$(date)] Sending email copy..." | tee -a "$LOG_FILE"
  python3 - <<PYEOF 2>&1 | tee -a "$LOG_FILE"
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

with open("$OUTPUT_FILE", "r") as f:
    body = f.read()

msg = MIMEMultipart()
msg["From"] = "$EMAIL_FROM"
msg["To"] = "$EMAIL_TO"
msg["Subject"] = "🛰️ AI Radar — $TODAY"
msg.attach(MIMEText(body, "plain", "utf-8"))

ctx = ssl.create_default_context()
with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
    server.login("$EMAIL_FROM", "$GMAIL_APP_PASSWORD")
    server.send_message(msg)
print("Email sent to $EMAIL_TO")
PYEOF
else
  echo "[$(date)] (email skipped — set AIRADAR_EMAIL_FROM + AIRADAR_GMAIL_APP_PASSWORD in .config.env to enable)" | tee -a "$LOG_FILE"
fi

echo "[$(date)] Daily run complete." | tee -a "$LOG_FILE"
