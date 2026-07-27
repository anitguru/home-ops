#!/usr/bin/env bash

# Shared crash-safe lock for the local naming and deterministic PARA stages.
# Callers should exit silently when acquire_para_pipeline_lock returns non-zero.

HERMES_PARA_LOCKDIR="${HERMES_PARA_LOCKDIR:-/tmp/hermes-para-file-pipeline.lock}"
HERMES_PARA_STALE_SECONDS="${HERMES_PARA_STALE_SECONDS:-3600}"
HERMES_PARA_LOCK_OWNED=0
HERMES_PARA_CHILD_PID=""
HERMES_PARA_OUTPUT_FILE=""
HERMES_PARA_OUTPUT=""

cleanup_para_pipeline_lock() {
  if [[ "$HERMES_PARA_CHILD_PID" =~ ^[0-9]+$ ]] && kill -0 "$HERMES_PARA_CHILD_PID" 2>/dev/null; then
    kill -TERM "$HERMES_PARA_CHILD_PID" 2>/dev/null || true
    wait "$HERMES_PARA_CHILD_PID" 2>/dev/null || true
  fi
  HERMES_PARA_CHILD_PID=""
  if [[ -n "$HERMES_PARA_OUTPUT_FILE" && -f "$HERMES_PARA_OUTPUT_FILE" ]]; then
    unlink "$HERMES_PARA_OUTPUT_FILE" 2>/dev/null || true
  fi
  HERMES_PARA_OUTPUT_FILE=""
  if [[ "$HERMES_PARA_LOCK_OWNED" != "1" ]]; then
    return 0
  fi
  if [[ -f "$HERMES_PARA_LOCKDIR/pid" ]]; then
    local owner
    owner="$(<"$HERMES_PARA_LOCKDIR/pid")"
    if [[ "$owner" == "$$" ]]; then
      unlink "$HERMES_PARA_LOCKDIR/pid" 2>/dev/null || true
    fi
  fi
  rmdir "$HERMES_PARA_LOCKDIR" 2>/dev/null || true
  HERMES_PARA_LOCK_OWNED=0
}

_claim_para_pipeline_lock() {
  if ! mkdir "$HERMES_PARA_LOCKDIR" 2>/dev/null; then
    return 1
  fi
  printf '%s\n' "$$" >"$HERMES_PARA_LOCKDIR/pid"
  HERMES_PARA_LOCK_OWNED=1
  trap cleanup_para_pipeline_lock EXIT
  trap 'cleanup_para_pipeline_lock; exit 143' HUP INT TERM
  return 0
}

acquire_para_pipeline_lock() {
  if _claim_para_pipeline_lock; then
    return 0
  fi

  local owner=""
  if [[ -f "$HERMES_PARA_LOCKDIR/pid" ]]; then
    owner="$(<"$HERMES_PARA_LOCKDIR/pid")"
  fi
  if [[ "$owner" =~ ^[0-9]+$ ]] && kill -0 "$owner" 2>/dev/null; then
    return 1
  fi

  # Old wrappers did not record an owner. Only reclaim such a lock after a
  # conservative age threshold so an in-flight legacy run cannot be stolen.
  if [[ -z "$owner" ]]; then
    local now modified age
    now="$(date +%s)"
    modified="$(stat -f %m "$HERMES_PARA_LOCKDIR" 2>/dev/null || printf '%s' "$now")"
    age=$((now - modified))
    if (( age < HERMES_PARA_STALE_SECONDS )); then
      return 1
    fi
  fi

  local stale="${HERMES_PARA_LOCKDIR}.stale.$$"
  if ! mv "$HERMES_PARA_LOCKDIR" "$stale" 2>/dev/null; then
    return 1
  fi
  if [[ -f "$stale/pid" ]]; then
    unlink "$stale/pid" 2>/dev/null || true
  fi
  rmdir "$stale" 2>/dev/null || true
  _claim_para_pipeline_lock
}

run_para_pipeline_command() {
  HERMES_PARA_OUTPUT_FILE="$(mktemp "${TMPDIR:-/tmp}/hermes-para-output.XXXXXX")"
  "$@" >"$HERMES_PARA_OUTPUT_FILE" 2>&1 &
  HERMES_PARA_CHILD_PID=$!
  local status=0
  if wait "$HERMES_PARA_CHILD_PID"; then
    status=0
  else
    status=$?
  fi
  HERMES_PARA_CHILD_PID=""
  HERMES_PARA_OUTPUT="$(<"$HERMES_PARA_OUTPUT_FILE")"
  unlink "$HERMES_PARA_OUTPUT_FILE" 2>/dev/null || true
  HERMES_PARA_OUTPUT_FILE=""
  return "$status"
}