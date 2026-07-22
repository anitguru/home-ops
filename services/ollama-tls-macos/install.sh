#!/bin/bash
set -euo pipefail

CADDY_VERSION="v2.11.4"
XCADDY_VERSION="v0.4.5"
BUNNY_MODULE_VERSION="v1.2.0"
LABEL="com.anitguru.ollama-tls"
REAL_HOME="/Users/sva"
SERVICE_DIR="$REAL_HOME/Documents/Repos/Github/home-ops/services/ollama-tls-macos"
RUNTIME_DIR="$REAL_HOME/Library/Application Support/ollama-tls-caddy"
BIN_DIR="$RUNTIME_DIR/bin"
CONFIG_DIR="$RUNTIME_DIR/config"
TOOLS_DIR="$RUNTIME_DIR/build-tools"
LOG_DIR="$REAL_HOME/Library/Logs/ollama-tls-caddy"
PLIST="$REAL_HOME/Library/LaunchAgents/$LABEL.plist"
CADDY="$BIN_DIR/caddy"
XCADDY="$TOOLS_DIR/xcaddy"
RUNNER="$BIN_DIR/run-caddy.sh"

command -v go >/dev/null 2>&1 || {
  echo "Go is required. Install it with: brew install go" >&2
  exit 1
}
[[ -x "$REAL_HOME/.local/bin/secret" ]] || {
  echo "SOPS secret helper is missing: $REAL_HOME/.local/bin/secret" >&2
  exit 1
}

mkdir -p "$BIN_DIR" "$CONFIG_DIR" "$TOOLS_DIR" "$LOG_DIR" "$REAL_HOME/Library/LaunchAgents"

needs_build=true
if [[ -x "$CADDY" ]] \
  && [[ "$("$CADDY" version | /usr/bin/awk '{print $1}')" == "$CADDY_VERSION" ]] \
  && "$CADDY" list-modules --packages | /usr/bin/grep -q '^dns.providers.bunny'; then
  needs_build=false
fi

if $needs_build; then
  printf 'Building xcaddy %s...\n' "$XCADDY_VERSION"
  GOBIN="$TOOLS_DIR" go install "github.com/caddyserver/xcaddy/cmd/xcaddy@$XCADDY_VERSION"

  printf 'Building Caddy %s with Bunny DNS module %s...\n' "$CADDY_VERSION" "$BUNNY_MODULE_VERSION"
  "$XCADDY" build "$CADDY_VERSION" \
    --with "github.com/caddy-dns/bunny@$BUNNY_MODULE_VERSION" \
    --output "$CADDY.new"
  chmod 0755 "$CADDY.new"
  mv "$CADDY.new" "$CADDY"
else
  printf 'Reusing existing Caddy %s with Bunny DNS module.\n' "$CADDY_VERSION"
fi

"$CADDY" list-modules --packages | /usr/bin/grep -q '^dns.providers.bunny'
BUNNY_API_KEY="$($REAL_HOME/.local/bin/secret bunny API_KEY)" \
  "$CADDY" validate --config "$SERVICE_DIR/Caddyfile" --adapter caddyfile

# Deploy only after the source configuration has validated successfully.
install -m 0755 "$SERVICE_DIR/run-caddy.sh" "$RUNNER"
install -m 0644 "$SERVICE_DIR/Caddyfile" "$CONFIG_DIR/Caddyfile"

python3 - "$PLIST" "$RUNNER" "$LOG_DIR" <<'PY'
import plistlib, sys
plist_path, runner, log_dir = sys.argv[1:]
data = {
    'Label': 'com.anitguru.ollama-tls',
    'ProgramArguments': [runner],
    'RunAtLoad': True,
    'KeepAlive': True,
    'ThrottleInterval': 10,
    'ProcessType': 'Background',
    'StandardOutPath': f'{log_dir}/stdout.log',
    'StandardErrorPath': f'{log_dir}/stderr.log',
}
with open(plist_path, 'wb') as f:
    plistlib.dump(data, f, sort_keys=False)
PY
chmod 0644 "$PLIST"
plutil -lint "$PLIST"

DOMAIN="gui/$UID"
SERVICE="$DOMAIN/$LABEL"

if launchctl print "$SERVICE" >/dev/null 2>&1; then
  launchctl bootout "$SERVICE"
  for _ in $(seq 1 20); do
    if ! launchctl print "$SERVICE" >/dev/null 2>&1; then
      break
    fi
    sleep 0.25
  done
fi

bootstrapped=false
for attempt in 1 2 3 4 5; do
  if bootstrap_error="$(launchctl bootstrap "$DOMAIN" "$PLIST" 2>&1)"; then
    bootstrapped=true
    break
  fi
  printf 'launchctl bootstrap attempt %d failed: %s\n' "$attempt" "$bootstrap_error" >&2
  sleep 1
done
if [[ "$bootstrapped" != true ]]; then
  echo "failed to bootstrap $LABEL after 5 attempts" >&2
  exit 1
fi

launchctl enable "$SERVICE"
launchctl kickstart -k "$SERVICE"

printf 'Installed and started %s\n' "$LABEL"
