#!/usr/bin/env bash
set -euo pipefail

HOST_ALIAS="${HERMES_DASHBOARD_HOST_ALIAS:-hermes-dashboard.transformers.lan}"
PORT="${HERMES_DASHBOARD_PORT:-9443}"
BIND_HOST="${HERMES_DASHBOARD_BIND_HOST:-0.0.0.0}"
LAN_IP="${HERMES_DASHBOARD_LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || true)}"
LAN_IP="${LAN_IP:-10.0.0.196}"
CERT="${HERMES_DASHBOARD_TLS_CERT:-$HOME/.hermes/dashboard/certs/hermes-dashboard.transformers.lan.crt}"
KEY="${HERMES_DASHBOARD_TLS_KEY:-$HOME/.hermes/dashboard/certs/hermes-dashboard.transformers.lan.key}"
HERMES_BIN="${HERMES_BIN:-$HOME/.local/bin/hermes}"
DNS_SERVER="${HERMES_DASHBOARD_DNS_SERVER:-10.0.0.1}"
ALLOWED_HOSTS="${HERMES_DASHBOARD_ALLOWED_HOSTS:-$HOST_ALIAS,localhost,127.0.0.1,$LAN_IP,mbp.transformers.lan}"

if [[ ! -f "$CERT" || ! -f "$KEY" ]]; then
  echo "Missing dashboard TLS cert/key:" >&2
  echo "  cert: $CERT" >&2
  echo "  key:  $KEY" >&2
  exit 1
fi

resolved="$(dig +short @"$DNS_SERVER" "$HOST_ALIAS" A 2>/dev/null | tail -n 1 || true)"
if [[ "$resolved" != "$LAN_IP" ]]; then
  cat >&2 <<EOF
Warning: $HOST_ALIAS does not resolve to $LAN_IP via $DNS_SERVER yet.
Create/repair the UniFi local DNS A record:
  $HOST_ALIAS -> $LAN_IP

Current $DNS_SERVER answer: ${resolved:-<none>}
EOF
fi

# LAN mode mirrors hermes-webui: listen on all interfaces, serve TLS directly,
# and allow only the trusted local hostnames through Hermes' Host-header checks.
(
  sleep 1
  open "https://${HOST_ALIAS}:${PORT}/" >/dev/null 2>&1 || true
) &

exec "$HERMES_BIN" dashboard \
  --tui \
  --host "$BIND_HOST" \
  --port "$PORT" \
  --no-open \
  --insecure \
  --tls-cert "$CERT" \
  --tls-key "$KEY" \
  --allowed-host "$ALLOWED_HOSTS"
