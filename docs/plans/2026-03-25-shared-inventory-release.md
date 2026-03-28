# Shared Inventory Release Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the `USD1-USDC` release-only leg automatically scale its sell-side release amount using shared `USD1` long inventory from the `USD1-USDT` main leg, while keeping local state synchronized through the shared route ledger.

**Architecture:** Keep the current multi-instance structure. Extend the release-only strategy path so it can read companion state snapshots, derive additional releasable shared inventory, and scale its release sell size. Keep the shared route ledger as the synchronization mechanism for reducing the main leg's recorded long inventory after the release leg executes.

**Tech Stack:** Python 3.12, Decimal, JSON state snapshots, pytest

---

### Task 1: Add shared release sizing tests

**Files:**
- Modify: `tests/test_strategy.py`

**Step 1: Write the failing test**

Add tests that verify:

- release-only mode increases release size when shared long inventory is available
- release-only mode still respects its own minimum buffer and does not exceed current target limits

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: FAIL because release-only mode ignores shared inventory.

**Step 3: Write minimal implementation**

Add shared release inventory inputs to state/config and use them in `_decide_release_only()`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: PASS

### Task 2: Add shared inventory snapshot plumbing

**Files:**
- Modify: `src/config.py`
- Modify: `src/state.py`
- Modify: `src/bot.py`
- Modify: `config/config.binance.usd1usdc.mainnet.yaml`

**Step 1: Add config fields**

Add release-only companion snapshot config, for example:

- `release_only_shared_state_paths`

**Step 2: Implement bot refresh**

When running a release-only leg:

- read companion state snapshots
- sum matching positive strategy inventory
- store the shared releasable amount in bot state

**Step 3: Persist state**

Persist shared release inventory into the state snapshot for visibility and debugging.

### Task 3: Verify end-to-end sync stays correct

**Files:**
- Modify: `tests/test_bot.py`
- Modify: `tests/test_state.py`

**Step 1: Add or extend tests**

Verify:

- release leg reads shared long inventory from companion state
- release leg can size above its local inventory when shared inventory exists
- route ledger application still reduces the main leg long inventory after fills

**Step 2: Run focused tests**

Run: `python3 -m pytest tests/test_strategy.py tests/test_state.py tests/test_bot.py -q`
Expected: PASS

### Task 4: Run full regression

**Files:**
- Modify: relevant files above

**Step 1: Run full suite**

Run: `python3 -m pytest tests -q`
Expected: PASS
