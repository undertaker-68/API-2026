#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/root/API-2026/ms-ozon-sync/.env"

set -a
source "$ENV_FILE"
set +a

CHAT_ID="${TG_NOTIFY_CHAT_ID:-${ALLOWED_CHAT_IDS%%,*}}"
TEXT="${1:-"(no message)"}"

curl -sS -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${TEXT}" >/dev/null
