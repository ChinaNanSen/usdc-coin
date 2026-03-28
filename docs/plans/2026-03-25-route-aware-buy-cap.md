# Route-Aware Buy Cap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a route-aware direct buy ceiling so rebalance buy orders do not overpay when the route engine says the indirect buy path is meaningfully cheaper.

**Architecture:** Extend the current route-aware pricing logic with a buy-side twin of the sell floor. Reuse existing route choice state and thresholds, and cap direct rebalance buy pricing using the route engine's preferred indirect reference price when no buy-side handoff exists.

**Tech Stack:** Python 3.12, Decimal, pytest

---

### Task 1: Add buy-cap strategy test

**Files:**
- Modify: `tests/test_strategy.py`

**Step 1: Write the failing test**

Add a test that verifies:

- when route choice says indirect buy is preferred,
- and direct buy cap is enabled,
- rebalance buy price is capped to the route reference price

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: FAIL because the buy-side route cap does not exist yet.

**Step 3: Write minimal implementation**

Add config field and route-aware buy ceiling in strategy pricing.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: PASS

### Task 2: Wire config defaults

**Files:**
- Modify: `src/config.py`
- Modify: `config/config.binance.usdc.mainnet.yaml`
- Modify: `config/config.binance.usd1usdt.mainnet.yaml`
- Modify: `config/config.example.yaml`

**Step 1: Add config field**

Add:

- `triangle_direct_buy_ceiling_enabled`

**Step 2: Set defaults**

Enable it for the Binance main legs.

### Task 3: Verify regressions

**Files:**
- Modify: relevant files above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_strategy.py tests/test_config.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
