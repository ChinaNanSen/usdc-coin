#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USDC_CONFIG="${USDC_CONFIG:-$ROOT_DIR/config/config.usdc.yaml}"
USDG_CONFIG="${USDG_CONFIG:-$ROOT_DIR/config/config.usdg.yaml}"
OBS_CONFIG="${OBS_CONFIG:-$ROOT_DIR/config/config.observe.yaml}"
OBS_QUOTE_SIZE="${OBS_QUOTE_SIZE:-5000}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"

resolve_python_cmd() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    PYTHON_CMD=("${PYTHON_BIN}")
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD=("python3")
    return 0
  fi

  if command -v py >/dev/null 2>&1; then
    PYTHON_CMD=("py" "-3")
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    PYTHON_CMD=("python")
    return 0
  fi

  return 1
}

if ! resolve_python_cmd; then
  echo "No usable Python interpreter found. Set PYTHON_BIN explicitly, for example:" >&2
  echo "  PYTHON_BIN=python3 bash scripts/run_dual_core.sh" >&2
  echo "  PYTHON_BIN='py -3' bash scripts/run_dual_core.sh" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

echo "Using Python interpreter: ${PYTHON_CMD[*]}"

echo "[1/3] Observe markets before startup"
"${PYTHON_CMD[@]}" "$ROOT_DIR/main.py" \
  --config "$OBS_CONFIG" \
  --observe-markets \
  --observe-quote-size "$OBS_QUOTE_SIZE"

echo "[2/3] Start USDC-USDT instance"
nohup "${PYTHON_CMD[@]}" "$ROOT_DIR/main.py" \
  --config "$USDC_CONFIG" \
  > "$LOG_DIR/usdc.out" 2>&1 &
USDC_PID=$!

echo "[3/3] Start USDG-USDT instance"
nohup "${PYTHON_CMD[@]}" "$ROOT_DIR/main.py" \
  --config "$USDG_CONFIG" \
  > "$LOG_DIR/usdg.out" 2>&1 &
USDG_PID=$!

echo "Started dual-core instances"
echo "  USDC-USDT pid: $USDC_PID log: $LOG_DIR/usdc.out"
echo "  USDG-USDT pid: $USDG_PID log: $LOG_DIR/usdg.out"
echo
echo "Use these commands to inspect:"
echo "  tail -f \"$LOG_DIR/usdc.out\""
echo "  tail -f \"$LOG_DIR/usdg.out\""
