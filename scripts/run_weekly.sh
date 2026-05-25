#!/usr/bin/env bash
# AI Radar — Weekly orchestrator
# Triggered by launchd Sunday 08:00 AM.

set -euo pipefail

RADAR_DIR="$HOME/ai-radar"
PROMPT_FILE="$RADAR_DIR/prompts/weekly_digest.md"
OUTPUT_DIR="$RADAR_DIR/output"
LOG_DIR="$RADAR_DIR/logs"
TODAY=$(date +%Y-%m-%d)
OUTPUT_FILE="$OUTPUT_DIR/weekly_$TODAY.md"
LOG_FILE="$LOG_DIR/weekly-$TODAY.log"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"

CONFIG_FILE="$RADAR_DIR/.config.env"
if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

EMAIL_TO="${AIRADAR_EMAIL_TO:-jim.liumingjing@gmail.com}"
EMAIL_FROM="${AIRADAR_EMAIL_FROM:-}"
GMAIL_APP_PASSWORD="${AIRADAR_GMAIL_APP_PASSWORD:-}"

# Collect last 7 days of daily outputs
DAILIES=()
for i in {0..6}; do
  D=$(date -v-${i}d +%Y-%m-%d 2>/dev/null || date -d "$i days ago" +%Y-%m-%d)
  F="$OUTPUT_DIR/$D.md"
  [[ -f "$F" ]] && DAILIES+=("$F")
done

if [[ ${#DAILIES[@]} -eq 0 ]]; then
  echo "[$(date)] No daily files in past 7 days — skipping weekly" | tee -a "$LOG_FILE"
  exit 0
fi

echo "[$(date)] Building weekly from ${#DAILIES[@]} dailies" | tee -a "$LOG_FILE"

DAILY_LIST=$(printf "%s\n" "${DAILIES[@]}")

claude -p "Execute the AI Radar weekly wrap per system prompt $PROMPT_FILE. Today is $TODAY. Read these daily output files: $DAILY_LIST. Synthesize into a weekly wrap. Write to $OUTPUT_FILE. Follow ALL workflow steps including the Discord push to chat_id 1484904539952775351 with the output file attached." \
  --allowedTools "Read,Write,mcp__plugin_discord_discord__reply" \
  2>&1 | tee -a "$LOG_FILE"

if [[ ! -f "$OUTPUT_FILE" ]]; then
  echo "ERROR: weekly output file not created" | tee -a "$LOG_FILE"
  exit 1
fi

# Optional email
if [[ -n "$EMAIL_FROM" && -n "$GMAIL_APP_PASSWORD" ]]; then
  python3 - <<PYEOF 2>&1 | tee -a "$LOG_FILE"
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

with open("$OUTPUT_FILE", "r") as f:
    body = f.read()

msg = MIMEMultipart()
msg["From"] = "$EMAIL_FROM"
msg["To"] = "$EMAIL_TO"
msg["Subject"] = "📅 AI Radar Weekly Wrap — $TODAY"
msg.attach(MIMEText(body, "plain", "utf-8"))

ctx = ssl.create_default_context()
with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
    server.login("$EMAIL_FROM", "$GMAIL_APP_PASSWORD")
    server.send_message(msg)
print("Weekly email sent")
PYEOF
fi

echo "[$(date)] Weekly run complete." | tee -a "$LOG_FILE"
