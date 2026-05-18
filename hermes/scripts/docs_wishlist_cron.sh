#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/sva/Documents/Repos/Github/home-ops/hermes/docs-wishlist"
HOME_OPS_HERMES_SCRIPTS="${HOME_OPS_HERMES_SCRIPTS:-/Users/sva/Documents/Repos/Github/home-ops/hermes/scripts}"
HERMES_PYTHON="${HERMES_PYTHON:-/Users/sva/.hermes/hermes-agent/venv/bin/python3}"
PYTHON="${PYTHON:-/Users/sva/Documents/Repos/Github/home-ops/.venv/bin/python}"
VAULT_ROOT_DEFAULT="/Users/sva/Documents/Dropbox/Obsidian/AnITGuru"
CA_BUNDLE_DEFAULT="/Users/sva/.hermes/certs/transformers-lan-ca-bundle.pem"

# Keep this deterministic by default and avoid nested/direct-provider leakage.
unset ANTHROPIC_API_KEY ANTHROPIC_TOKEN CLAUDE_API_KEY
unset HERMES_TUI HERMES_TUI_ACTIVE_SESSION_FILE HERMES_GATEWAY_SESSION HERMES_INTERACTIVE HERMES_SESSION_KEY

if [[ -f "$HOME/.hermes/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$HOME/.hermes/.env"
  set +a
fi

if [[ ! -x "$HERMES_PYTHON" ]]; then
  echo "ERROR: expected Hermes venv Python at $HERMES_PYTHON" >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: expected home-ops venv Python at $PYTHON" >&2
  echo "Create it with: $HERMES_PYTHON -m venv /Users/sva/Documents/Repos/Github/home-ops/.venv && /Users/sva/Documents/Repos/Github/home-ops/.venv/bin/pip install -r /Users/sva/Documents/Repos/Github/home-ops/hermes/scripts/requirements.txt" >&2
  exit 1
fi

cd "$ROOT"

export HOME_OPS_HERMES_SCRIPTS
export VAULT_ROOT="${VAULT_ROOT:-$VAULT_ROOT_DEFAULT}"
export OBSIDIAN_MCP_VAULT="${OBSIDIAN_MCP_VAULT:-personal}"
export RSS_INGEST_USE_LLM="${RSS_INGEST_USE_LLM:-0}"
export FIRECRAWL_URL="${FIRECRAWL_URL:-${FIRECRAWL_API_URL:-https://10.0.0.53}}"
export FIRECRAWL_API_KEY="${FIRECRAWL_API_KEY:-${FIRECRAWL_API_TOKEN:-}}"
if [[ -f "$CA_BUNDLE_DEFAULT" ]]; then
  export FIRECRAWL_CA_BUNDLE="${FIRECRAWL_CA_BUNDLE:-$CA_BUNDLE_DEFAULT}"
  export SSL_CERT_FILE="${SSL_CERT_FILE:-$CA_BUNDLE_DEFAULT}"
fi

run_site() {
  local site="$1"
  shift
  echo "--- docs wishlist: $site ---"
  "$PYTHON" rss_ingest.py "$@" --sites-config docs-sites.json --wishlist "$site"
}

if [[ "${1:-}" == "--check" ]]; then
  "$PYTHON" -m py_compile rss_ingest.py "$HOME_OPS_HERMES_SCRIPTS/hermes_llm.py"
  "$PYTHON" rss_ingest.py --help >/dev/null
  "$PYTHON" rss_ingest.py --dry-run --wishlist react --cap 0 --sites-config docs-sites.json
  echo "docs_wishlist_cron check ok"
  exit 0
fi

SITE="all"
CAP="5"
DRY_FLAG="--no-dry-run"
FORCE_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site)
      SITE="${2:?--site requires a value}"
      shift 2
      ;;
    --cap)
      CAP="${2:?--cap requires a value}"
      shift 2
      ;;
    --no-dry-run)
      DRY_FLAG="--no-dry-run"
      shift
      ;;
    --dry-run)
      DRY_FLAG="--dry-run"
      shift
      ;;
    --force)
      FORCE_FLAG="--force"
      shift
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

COMMON_ARGS=("$DRY_FLAG" --cap "$CAP")
if [[ -n "$FORCE_FLAG" ]]; then
  COMMON_ARGS+=("$FORCE_FLAG")
fi

if [[ "$SITE" == "all" ]]; then
  for site in astro tailwind typescript react; do
    run_site "$site" "${COMMON_ARGS[@]}"
  done
else
  run_site "$SITE" "${COMMON_ARGS[@]}"
fi

echo "home-ops docs-wishlist run complete (Hermes cron only; no Gitea Actions, runners, Git push/writeback, Obsidian MCP dependency, or direct provider calls by default)"
