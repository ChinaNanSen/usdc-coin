# Indirect Release Gate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add thresholds for shared-inventory release expansion and block direct rebalance sells on the main leg when indirect release is clearly preferred.

**Architecture:** Keep the current multi-instance collaboration model. Extend config with explicit indirect-preference thresholds, make the release leg consume shared inventory only above those thresholds, and make the main leg suppress direct sell rebalance intents when the route engine says indirect release should take over.

**Tech Stack:** Python 3.12, Decimal, pytest

---

### Task 1: Add thresholded shared release tests

**Files:**
- Modify: `tests/test_bot.py`
- Modify: `tests/test_strategy.py`

**Step 1: Write the failing test**

Add tests that verify:

- release leg ignores companion shared inventory when improvement is too small
- main leg suppresses direct sell rebalance when indirect route is clearly preferred

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_strategy.py tests/test_bot.py -q`
Expected: FAIL because thresholds and suppress gate do not exist yet.

**Step 3: Write minimal implementation**

Add config fields, apply thresholds, and suppress direct sell rebalance under indirect-preferred route choice.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_strategy.py tests/test_bot.py -q`
Expected: PASS

### Task 2: Wire config fields

**Files:**
- Modify: `src/config.py`
- Modify: `config/config.binance.usd1usdt.mainnet.yaml`
- Modify: `config/config.binance.usd1usdc.mainnet.yaml`
- Modify: `config/config.example.yaml`

**Step 1: Add config fields**

Add:

- `triangle_prefer_indirect_min_improvement_bp`
- `release_only_shared_inventory_min_base`
- `release_only_shared_inventory_min_improvement_bp`

**Step 2: Enable sensible defaults**

Set practical defaults in Binance configs.

### Task 3: Verify regressions

**Files:**
- Modify: relevant tests above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_strategy.py tests/test_bot.py tests/test_state.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
