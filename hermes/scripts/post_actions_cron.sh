#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/sva/Documents/Repos/Github/home-ops/hermes/x-social"
HOME_OPS_HERMES_SCRIPTS="${HOME_OPS_HERMES_SCRIPTS:-/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts}"
HERMES_PYTHON="${HERMES_PYTHON:-/Users/sva/.hermes/hermes-agent/venv/bin/python3}"
PYTHON="${PYTHON:-/Users/sva/Documents/Repos/Github/home-ops/.venv/bin/python}"
X_SOCIAL_STATE_DIR="${X_SOCIAL_STATE_DIR:-${HERMES_STATE_DIR:-$HOME/.local/state/home-ops}/x-social}"

cd "$ROOT"

if [[ ! -x "$HERMES_PYTHON" ]]; then
  echo "ERROR: expected Hermes venv Python at $HERMES_PYTHON" >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: expected home-ops venv Python at $PYTHON" >&2
  echo "Create it with: $HERMES_PYTHON -m venv /Users/sva/Documents/Repos/Github/home-ops/.venv && /Users/sva/Documents/Repos/Github/home-ops/.venv/bin/pip install -r $ROOT/requirements.txt" >&2
  exit 1
fi

if [[ "${1:-}" == "--check" ]]; then
  "$HERMES_PYTHON" "$HOME_OPS_HERMES_SCRIPTS/sops_env.py" --purpose post --check
  "$PYTHON" -m py_compile scripts/fetch_metrics.py scripts/post.py scripts/social_db.py
  env -u HERMES_TUI -u HERMES_TUI_ACTIVE_SESSION_FILE -u HERMES_GATEWAY_SESSION -u HERMES_INTERACTIVE -u HERMES_SESSION_KEY \
    hermes -p xposting chat -Q --source xposting-cron-check --provider xai-oauth -m grok-4.3 --toolsets terminal \
      -q 'Use terminal to print exactly: xposting grok profile ready'
  echo "post_actions_cron check ok"
  exit 0
fi

# Load X/Tavily/Postgres secrets from the local SOPS+age store without writing plaintext to disk.
eval "$("$HERMES_PYTHON" "$HOME_OPS_HERMES_SCRIPTS/sops_env.py" --purpose post)"

export HOME_OPS_HERMES_SCRIPTS
export X_SOCIAL_STATE_DIR
export HERMES_AUTOMATION_PROFILE="${HERMES_POSTING_PROFILE:-xposting}"
# Grok is safe here because this one-shot profile is constrained to a tiny toolset.
# Do not make Grok the default Telegram/provider profile unless Hermes has <200 exposed tools.
export HERMES_AUTOMATION_TOOLSETS="${HERMES_AUTOMATION_TOOLSETS:-terminal}"
export HERMES_POSTING_PROVIDER="${HERMES_POSTING_PROVIDER:-xai-oauth}"
export HERMES_POSTING_MODEL="${HERMES_POSTING_MODEL:-grok-4.3}"
export POST_USE_LLM="${POST_USE_LLM:-1}"

"$PYTHON" scripts/fetch_metrics.py
"$PYTHON" scripts/post.py

echo "home-ops x-social state updated locally under $X_SOCIAL_STATE_DIR (Hermes cron only; no external runner or Git network writes)"
