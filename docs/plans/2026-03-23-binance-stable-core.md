# Binance Stable Core Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Binance stablecoin production skeleton with `USDC-USDT` as the main engine, `USD1-USDT` as the secondary engine, and `USD1-USDC` as an optional small-cap release leg.

**Architecture:** Keep the existing single-market bot architecture. Implement the first production layer through per-pair configs plus a single wrapper script that observes the three Binance markets before launching the first two core instances, while gating the third release leg behind an environment switch.

**Tech Stack:** Python 3.12, YAML configs, Bash scripts, pytest

---

### Task 1: Switch Binance observer defaults

**Files:**
- Modify: `src/market_observer.py`
- Modify: `tests/test_market_observer.py`

**Step 1: Write the failing test**

Add a test that verifies:

- when `config.exchange.name == "binance"` and `inst_ids` is omitted,
- the observer defaults to `USDC-USDT`, `USD1-USDT`, and `USD1-USDC`

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_market_observer.py -q`
Expected: FAIL because observer still defaults to the OKX market list.

**Step 3: Write minimal implementation**

Make observer defaults exchange-aware while preserving the current OKX default set.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_market_observer.py -q`
Expected: PASS

### Task 2: Add Binance stablecoin configs

**Files:**
- Create: `config/config.binance.observe.yaml`
- Create: `config/config.binance.usd1usdt.mainnet.yaml`
- Create: `config/config.binance.usd1usdc.mainnet.yaml`
- Modify: `config/config.binance.usdc.mainnet.yaml`

**Step 1: Write the config files**

Create the three Binance config files with:

- Binance mainnet exchange
- zero-fee gates
- disabled secondary layers
- distinct telemetry paths and managed prefixes
- conservative budgets for `USD1-USDT` and `USD1-USDC`

**Step 2: Smoke-load the configs**

Run: `python3 - <<'PY' ... load_config(...) ... PY`
Expected: all configs load and print their `inst_id` / telemetry target paths.

### Task 3: Add Binance stable-core run/stop scripts

**Files:**
- Create: `scripts/run_binance_stable_core.sh`
- Create: `scripts/stop_binance_stable_core.sh`

**Step 1: Write the scripts**

Add a run script that:

- resolves Python robustly on Windows Git Bash
- runs market observation for the 3 Binance stable pairs
- starts `USDC-USDT`
- starts `USD1-USDT`
- starts `USD1-USDC` only when `START_USD1_USDC=1`

Add a stop script that:

- writes stop request files for all three instances
- waits for exit
- supports `FORCE_KILL=1`

**Step 2: Run shell syntax check**

Run: `bash -n scripts/run_binance_stable_core.sh scripts/stop_binance_stable_core.sh`
Expected: PASS

### Task 4: Verify integrated behavior

**Files:**
- Modify: none or relevant tests from above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_market_observer.py tests/test_config.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS

**Step 3: Run observer smoke**

Run: `python3 main.py --config config/config.binance.observe.yaml --observe-markets`
Expected: prints Binance `USDC-USDT / USD1-USDT / USD1-USDC` observation output.
