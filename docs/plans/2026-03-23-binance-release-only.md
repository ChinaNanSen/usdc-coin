# Binance Release-Only Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn `USD1-USDC` into a real release-only leg that activates only when external `USD1` inventory is above a configured buffer, while keeping local state accounting aligned with actual trading.

**Architecture:** Add a small release-only mode to the strategy/config path and a matching external-inventory accounting mode to `BotState`. Release-only sells consume tracked external inventory before creating any strategy short lots, and balance refreshes clamp the tracked external inventory to real account balances so the persisted state cannot drift above reality.

**Tech Stack:** Python 3.12, Decimal, YAML config, pytest

---

### Task 1: Add release-only strategy tests

**Files:**
- Modify: `tests/test_strategy.py`

**Step 1: Write the failing test**

Add tests that verify:

- release-only mode with enough external base inventory emits ask-only `release_external_long`
- release-only mode below the configured buffer emits no quote

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: FAIL because release-only mode does not exist yet.

**Step 3: Write minimal implementation**

Add release-only config flags and a release-only decision branch in `MicroMakerStrategy`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: PASS

### Task 2: Add external release accounting tests

**Files:**
- Modify: `tests/test_state.py`

**Step 1: Write the failing test**

Add tests that verify:

- release-tracking sell fills consume external inventory first
- normal external release does not create a negative strategy position
- balance refresh clamps external inventory remaining to real base balance

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_state.py -q`
Expected: FAIL because state does not support release-tracking accounting.

**Step 3: Write minimal implementation**

Add release tracking state configuration and accounting adjustments in `BotState`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_state.py -q`
Expected: PASS

### Task 3: Wire config and bot setup

**Files:**
- Modify: `src/config.py`
- Modify: `src/bot.py`
- Modify: `src/log_labels.py`
- Modify: `config/config.binance.usd1usdc.mainnet.yaml`

**Step 1: Implement config fields**

Add:

- `strategy.release_only_mode`
- `strategy.release_only_base_buffer`

and make the bot pass release-tracking config into state during startup.

**Step 2: Update release-leg config**

Set `USD1-USDC` config to:

- `release_only_mode: true`
- a conservative `release_only_base_buffer`
- no change to the first two engines

**Step 3: Run focused load test**

Run: `python3 - <<'PY' ... load_config('config/config.binance.usd1usdc.mainnet.yaml') ... PY`
Expected: release-only config loads with the new fields.

### Task 4: Verify regression and smoke behavior

**Files:**
- Modify: relevant tests above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_strategy.py tests/test_state.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
