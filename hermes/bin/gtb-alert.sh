#!/usr/bin/env bash
# systemd OnFailure backstop -> Telegram. Arg $1 = failed unit name.
export PATH=/home/pi/.local/bin:/usr/local/bin:/usr/bin:/bin
BOT_TOKEN="$(/home/pi/.local/bin/secret telegram BOT_TOKEN)"
UNIT="${1:-unknown}"
curl -sf "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
  --data-urlencode "chat_id=8100669692" \
  --data-urlencode "text=🔴 pi4 systemd unit failed: $UNIT — check: journalctl --user -u $UNIT -n 40" >/dev/null || true
