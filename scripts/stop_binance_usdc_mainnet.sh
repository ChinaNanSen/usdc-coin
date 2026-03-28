#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATTERN="${CONFIG_PATTERN:-config.binance.usdc.mainnet.yaml}"
STOP_FILE="${STOP_FILE:-$ROOT_DIR/trend_bot_6/data/binance_usdc/stop.live.request}"
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

find_pids() {
  if resolve_powershell; then
    "$POWERSHELL_CMD" -NoProfile -Command \
      "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*${CONFIG_PATTERN}*' } | Select-Object -ExpandProperty ProcessId" \
      2>/dev/null | tr -d '\r' | awk 'NF > 0 {print $1}'
    return 0
  fi
  ps -ef | grep -F "$CONFIG_PATTERN" | grep -v grep | awk '{print $2}'
}

mkdir -p "$(dirname "$STOP_FILE")"
: > "$STOP_FILE"
echo "Stop requested via $STOP_FILE"

pids="$(find_pids || true)"
if [[ -z "$pids" ]]; then
  echo "No running Binance USDC mainnet process matched."
  exit 0
fi

waited=0
while [[ $waited -lt $WAIT_SECONDS ]]; do
  sleep 1
  waited=$((waited + 1))
  pids="$(find_pids || true)"
  if [[ -z "$pids" ]]; then
    echo "Exited gracefully."
    exit 0
  fi
done

echo "Still running after ${WAIT_SECONDS}s."
if [[ "$FORCE_KILL" != "1" ]]; then
  echo "Not force-killing. Re-run with FORCE_KILL=1 if needed."
  exit 0
fi

echo "Force killing: $pids"
if resolve_powershell; then
  joined_ids="$(printf '%s\n' "$pids" | paste -sd, -)"
  "$POWERSHELL_CMD" -NoProfile -Command "Stop-Process -Id ${joined_ids} -Force" >/dev/null 2>&1 || true
else
  kill -9 $pids 2>/dev/null || true
fi
