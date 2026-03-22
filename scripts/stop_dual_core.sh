#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"
USDC_STOP_FILE="${USDC_STOP_FILE:-$ROOT_DIR/trend_bot_6/data/usdc/stop.sim.request}"
USDG_STOP_FILE="${USDG_STOP_FILE:-$ROOT_DIR/trend_bot_6/data/usdg/stop.sim.request}"
WAIT_SECONDS="${WAIT_SECONDS:-20}"
FORCE_KILL="${FORCE_KILL:-0}"

have_command() {
  command -v "$1" >/dev/null 2>&1
}

resolve_powershell() {
  if have_command powershell; then
    POWERSHELL_CMD="powershell"
    return 0
  fi
  if have_command powershell.exe; then
    POWERSHELL_CMD="powershell.exe"
    return 0
  fi
  return 1
}

find_pids_windows() {
  local pattern="$1"
  local output
  output="$(
    "$POWERSHELL_CMD" -NoProfile -Command \
      "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*${pattern}*' } | Select-Object -ExpandProperty ProcessId" \
      2>/dev/null || true
  )"
  printf '%s\n' "$output" | tr -d '\r' | awk 'NF > 0 {print $1}'
}

find_pids_posix() {
  local pattern="$1"
  ps -ef | grep -F "$pattern" | grep -v grep | awk '{print $2}'
}

find_pids() {
  local pattern="$1"
  if resolve_powershell; then
    find_pids_windows "$pattern"
    return 0
  fi

  find_pids_posix "$pattern"
}

stop_pattern() {
  local label="$1"
  local pattern="$2"
  local stop_file="$3"
  local pids
  mkdir -p "$(dirname "$stop_file")"
  : > "$stop_file"
  echo "$label: stop requested via $stop_file"
  pids="$(find_pids "$pattern" || true)"
  if [[ -z "$pids" ]]; then
    echo "$label: no running process matched, request file left in place for next matching process cycle"
    return 0
  fi

  local waited=0
  while [[ $waited -lt $WAIT_SECONDS ]]; do
    sleep 1
    waited=$((waited + 1))
    pids="$(find_pids "$pattern" || true)"
    if [[ -z "$pids" ]]; then
      echo "$label: exited gracefully"
      return 0
    fi
  done

  echo "$label: still running after ${WAIT_SECONDS}s"
  if [[ "$FORCE_KILL" != "1" ]]; then
    echo "$label: not force-killing. If you really want to kill it, rerun with FORCE_KILL=1."
    return 0
  fi

  echo "$label: force killing $pids"
  if resolve_powershell; then
    local joined_ids
    joined_ids="$(printf '%s\n' "$pids" | paste -sd, -)"
    "$POWERSHELL_CMD" -NoProfile -Command "Stop-Process -Id ${joined_ids} -Force" >/dev/null 2>&1 || true
    return 0
  fi

  kill -9 $pids 2>/dev/null || true
}

stop_pattern "USDC-USDT" "config/config.usdc.yaml" "$USDC_STOP_FILE"
stop_pattern "USDG-USDT" "config/config.usdg.yaml" "$USDG_STOP_FILE"

echo "Stop request sent."
echo "If any process is still alive, inspect with:"
echo "  ps -ef | grep -E 'config/config.usdc.yaml|config/config.usdg.yaml' | grep -v grep"
