#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

resolve_python_cmd() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    PYTHON_CMD=("${PYTHON_BIN}")
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    if python --version >/dev/null 2>&1; then
      PYTHON_CMD=("python")
      return 0
    fi
  fi

  if command -v py >/dev/null 2>&1; then
    if py -3 --version >/dev/null 2>&1; then
      PYTHON_CMD=("py" "-3")
      return 0
    fi
  fi

  if command -v python3 >/dev/null 2>&1; then
    if python3 --version >/dev/null 2>&1; then
      PYTHON_CMD=("python3")
      return 0
    fi
  fi

  if command -v python.exe >/dev/null 2>&1; then
    PYTHON_CMD=("python.exe")
    return 0
  fi

  if command -v py.exe >/dev/null 2>&1; then
    PYTHON_CMD=("py.exe" "-3")
    return 0
  fi

  return 1
}

if ! resolve_python_cmd; then
  echo "No usable Python interpreter found." >&2
  echo "Set PYTHON_BIN explicitly, for example:" >&2
  echo "  PYTHON_BIN=python bash scripts/run_okx_binance_usdc_arb_scan.sh" >&2
  echo "  PYTHON_BIN='py -3' bash scripts/run_okx_binance_usdc_arb_scan.sh" >&2
  exit 1
fi

echo "Using Python interpreter: ${PYTHON_CMD[*]}"
"${PYTHON_CMD[@]}" "$ROOT_DIR/scripts/okx_binance_usdc_arb_scan.py" "$@"
