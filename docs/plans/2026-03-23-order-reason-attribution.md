# Order Reason Attribution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a reason-based attribution tool that breaks down fills, turnover, realized PnL, and markout by action bucket (`entry`, `rebalance`, `secondary`, `release`) so the strategy can be diagnosed with direct evidence instead of aggregate PnL.

**Architecture:** Reuse existing journal and state outputs. First, add reason tagging to new order lifecycle events and markout tracking so future data is exact. Then add a standalone attribution analyzer that can read historical journals and produce best-effort breakdowns for existing runs. Keep the analyzer separate from the trading bot so it cannot affect live behavior.

**Tech Stack:** Python 3.12, Decimal, JSONL, pytest

---

### Task 1: Add Shared Reason Bucket Classifier

**Files:**
- Create: `src/reason_attribution.py`
- Test: `tests/test_order_reason_attribution.py`

**Step 1: Write the failing test**

Add a test that verifies reason strings map to:
- `join_best_*` -> `entry`
- `rebalance_open_*` -> `rebalance`
- `rebalance_secondary_*` -> `secondary`

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_order_reason_attribution.py -q`
Expected: FAIL because the classifier does not exist yet.

**Step 3: Write minimal implementation**

Add a small shared module for reason bucket classification and per-10k turnover calculation.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_order_reason_attribution.py -q`
Expected: PASS

### Task 2: Persist Reason Metadata On New Orders

**Files:**
- Modify: `src/executor.py`
- Modify: `src/state.py`
- Modify: `src/bot.py`
- Test: `tests/test_bot.py`
- Test: `tests/test_state.py`

**Step 1: Write the failing test**

Add tests that:
- set a reason on placed orders
- preserve reason metadata through order updates
- include reason bucket in emitted `order_update` journal events

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bot.py tests/test_state.py -q`
Expected: FAIL because state does not store reason metadata yet.

**Step 3: Write minimal implementation**

Store order reasons by `clOrdId`, tag `place_order` / `amend_order` events, and include `reason` and `reason_bucket` in `order_update` journal events.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bot.py tests/test_state.py -q`
Expected: PASS

### Task 3: Split Fill Markout By Reason Bucket

**Files:**
- Modify: `src/state.py`
- Test: `tests/test_state.py`

**Step 1: Write the failing test**

Add a state test that records a fill with an order reason and verifies markout samples are also accumulated under a reason bucket summary.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_state.py -q`
Expected: FAIL because reason-level markout summary does not exist yet.

**Step 3: Write minimal implementation**

Extend pending fill markout tracking so each sample keeps a reason bucket and expose `fill_markout_summary_by_reason()`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_state.py -q`
Expected: PASS

### Task 4: Add Standalone Attribution Analyzer

**Files:**
- Create: `src/order_reason_attribution.py`
- Create: `scripts/order_reason_attribution.py`
- Test: `tests/test_order_reason_attribution.py`

**Step 1: Write the failing test**

Add a test that feeds a tiny synthetic journal and asserts:
- turnover is grouped by bucket
- realized PnL is grouped by bucket
- reason-level markout is attached when available

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_order_reason_attribution.py -q`
Expected: FAIL because the analyzer does not exist yet.

**Step 3: Write minimal implementation**

Implement a best-effort analyzer that:
- replays journal events in run order
- infers reasons from `place_order`, `amend_order_submitted`, and recent decisions
- computes fill turnover and FIFO realized PnL per bucket
- merges in reason-level markout from the latest state snapshot if present

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_order_reason_attribution.py -q`
Expected: PASS

### Task 5: Verify And Run On Real Journal Data

**Files:**
- Modify: none or relevant tests from above

**Step 1: Run focused verification**

Run: `python3 -m pytest tests/test_order_reason_attribution.py tests/test_bot.py tests/test_state.py tests/test_executor_keep_partial.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS

**Step 3: Run analyzer on current USDC journal**

Run: `python3 scripts/order_reason_attribution.py --journal data/usdc/journal.sim.jsonl --state data/usdc/state_snapshot.sim.json`
Expected: prints bucketed fills, turnover, realized PnL, and markout summaries.
