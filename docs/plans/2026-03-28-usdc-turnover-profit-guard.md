# USDC Turnover Profit Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a long-inventory sell-drought guard and rebalance amend fallback to improve turnover and reduce stale inventory lockups.

**Architecture:** Extend `BotState` with minimal fill-timestamp tracking, use strategy-level gating to suppress new entry buys during long-inventory sell droughts, and let executor degrade rebalance amend failures into cancel-and-reconcile behavior. Keep changes local to config, state, strategy, executor, and focused regression tests.

**Tech Stack:** Python 3, pytest, dataclass config, existing OKX/strategy/executor abstractions

---

### Task 1: Add Config Surface

**Files:**
- Modify: `src/config.py`
- Modify: `config/config.usdc.yaml`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add config coverage that asserts the new strategy knobs load and parse correctly for decimal and integer values.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -q`

**Step 3: Write minimal implementation**

Add:

- `sell_drought_guard_enabled: bool = False`
- `sell_drought_inventory_ratio_pct: Decimal = Decimal("0.60")`
- `sell_drought_rebalance_window_seconds: float = 900.0`

Enable them in `config/config.usdc.yaml`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -q`

**Step 5: Commit**

Skip commit in this session unless explicitly requested.

### Task 2: Track Last Fill Timestamp By Side And Bucket

**Files:**
- Modify: `src/state.py`
- Test: `tests/test_state.py`

**Step 1: Write the failing test**

Add state coverage that a managed fill updates a `rebalance/sell` timestamp and that snapshot persistence restores it.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_state.py -q`

**Step 3: Write minimal implementation**

Add:

- an internal timestamp map keyed by `bucket + side`
- update logic inside managed fill processing
- accessors for fill age / latest fill timestamp
- snapshot persistence and restore

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_state.py -q`

**Step 5: Commit**

Skip commit in this session unless explicitly requested.

### Task 3: Add Sell-Drought Strategy Guard

**Files:**
- Modify: `src/strategy.py`
- Test: `tests/test_strategy.py`

**Step 1: Write the failing test**

Add tests for:

- suppressing `join_best_bid` during long-inventory rebalance-sell drought
- still allowing sell-side rebalance under the same condition
- keeping old behavior when the drought condition is not met

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy.py -q`

**Step 3: Write minimal implementation**

Add a helper that activates only when:

- sell drought guard is enabled
- strategy inventory is long
- inventory ratio exceeds threshold
- rebalance sell inventory exists
- last rebalance sell fill is older than configured window

Use it only to suppress new entry buys.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_strategy.py -q`

**Step 5: Commit**

Skip commit in this session unless explicitly requested.

### Task 4: Add Rebalance Amend Failure Fallback

**Files:**
- Modify: `src/executor.py`
- Test: `tests/test_okx_rest.py`
- Test: `tests/test_bot.py`

**Step 1: Write the failing test**

Add executor/bot coverage that:

- rebalance amend failure returns control to cancel path
- stale rebalance order is canceled instead of silently preserved
- existing entry amend failure behavior remains unchanged

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_okx_rest.py tests/test_bot.py -q`

**Step 3: Write minimal implementation**

Add executor logic so rebalance amend failures do not short-circuit stale-order cleanup. Keep journaling unchanged and let reconcile cancel the stale order when amend fails.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_okx_rest.py tests/test_bot.py -q`

**Step 5: Commit**

Skip commit in this session unless explicitly requested.

### Task 5: Run Focused Verification

**Files:**
- Modify: `none`
- Test: `tests/test_config.py`
- Test: `tests/test_state.py`
- Test: `tests/test_strategy.py`
- Test: `tests/test_okx_rest.py`
- Test: `tests/test_bot.py`

**Step 1: Run the focused suite**

Run:

```bash
pytest tests/test_config.py tests/test_state.py tests/test_strategy.py tests/test_okx_rest.py tests/test_bot.py -q
```

**Step 2: Read full output**

Confirm zero failures and note any skipped tests.

**Step 3: Summarize residual risk**

Record any remaining unverified areas, especially live OKX stream behavior that unit tests do not cover.

**Step 4: Commit**

Skip commit in this session unless explicitly requested.
