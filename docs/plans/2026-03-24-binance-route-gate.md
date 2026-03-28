# Binance Route Gate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a route-aware entry gate for Binance `USDC-USDT` and `USD1-USDT` so buy-side maker quotes are only posted when the current three-market snapshot offers acceptable dual-exit quality.

**Architecture:** Add a small triangle-routing module, store a route snapshot in bot state, refresh that snapshot periodically from the bot, and apply the resulting dual-exit gate inside the existing strategy before emitting buy-side entry intents. Keep `USD1-USDC` as a release-only leg and do not implement cross-market auto-exit yet.

**Tech Stack:** Python 3.12, Decimal, pytest

---

### Task 1: Add triangle routing math tests

**Files:**
- Create: `tests/test_triangle_routing.py`
- Create: `src/triangle_routing.py`

**Step 1: Write the failing test**

Add tests that verify:

- `USD1-USDT` dual-exit metrics are computed correctly
- `USDC-USDT` dual-exit metrics are computed correctly
- unsupported markets return no metrics

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_triangle_routing.py -q`
Expected: FAIL because the routing module does not exist yet.

**Step 3: Write minimal implementation**

Implement normalized snapshot building and dual-exit metric computation.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_triangle_routing.py -q`
Expected: PASS

### Task 2: Add strategy gate tests

**Files:**
- Modify: `tests/test_strategy.py`
- Modify: `src/strategy.py`
- Modify: `src/state.py`

**Step 1: Write the failing test**

Add tests that verify:

- route gate suppresses a low-quality Binance buy entry
- route gate allows a high-quality Binance buy entry

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: FAIL because strategy ignores route metrics.

**Step 3: Write minimal implementation**

Add route snapshot storage to state and apply route-aware gating to entry buy intents.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: PASS

### Task 3: Refresh route snapshot from bot

**Files:**
- Modify: `src/bot.py`
- Modify: `src/config.py`
- Modify: relevant Binance configs

**Step 1: Add config fields**

Add route-gate config:

- `triangle_routing_enabled`
- `triangle_route_refresh_interval_seconds`
- `triangle_snapshot_stale_ms`
- `triangle_strict_dual_exit_edge_bp`
- `triangle_best_exit_edge_bp`
- `triangle_max_worst_exit_loss_bp`
- `triangle_indirect_leg_penalty_bp`

**Step 2: Implement bot refresh**

Refresh the two auxiliary books periodically for supported Binance markets and store the snapshot in state.

**Step 3: Enable in Binance core configs**

Turn on route gating for:

- `config/config.binance.usdc.mainnet.yaml`
- `config/config.binance.usd1usdt.mainnet.yaml`

Leave `USD1-USDC` unchanged.

### Task 4: Verify regressions

**Files:**
- Modify: relevant files above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_triangle_routing.py tests/test_strategy.py tests/test_bot.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
