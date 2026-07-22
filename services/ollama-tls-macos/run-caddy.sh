#!/bin/bash
set -euo pipefail

REAL_HOME="/Users/sva"
RUNTIME_DIR="$REAL_HOME/Library/Application Support/ollama-tls-caddy"
CADDY="$RUNTIME_DIR/bin/caddy"
CONFIG="$RUNTIME_DIR/config/Caddyfile"
SECRET_HELPER="$REAL_HOME/.local/bin/secret"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [[ ! -x "$CADDY" ]]; then
  echo "missing Caddy binary: $CADDY" >&2
  exit 1
fi
if [[ ! -r "$CONFIG" ]]; then
  echo "missing Caddy config: $CONFIG" >&2
  exit 1
fi

# Load the Bunny API key from SOPS only at process start. The key is never
# written into the Caddyfile, LaunchAgent plist, or repository.
BUNNY_API_KEY="$($SECRET_HELPER bunny API_KEY)"
export BUNNY_API_KEY

# Isolate Caddy's ACME account, certificates, and state from other services.
export HOME="$RUNTIME_DIR/home"
umask 077
mkdir -p "$HOME"

exec "$CADDY" run --config "$CONFIG" --adapter caddyfile
