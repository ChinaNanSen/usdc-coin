# Budget Isolation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-instance balance budgets so `USDC-USDT` and `USDG-USDT` can run on the same OKX account without each instance treating the full account balance as its own.

**Architecture:** Keep the existing single-market bot structure. Introduce configured per-instance base/quote balance caps, track raw exchange balances separately from effective instance balances, and make risk/execution use the effective balances that are capped by both the exchange balance and the instance budget. Add bootstrap validation so an instance refuses to start when its configured budget exceeds the account's current balance.

**Tech Stack:** Python 3.12, dataclasses, Decimal, pytest

---

### Task 1: Add Budget Config Fields

**Files:**
- Modify: `config/config.yaml`
- Modify: `config/config.example.yaml`
- Modify: `src/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add a config test that loads `budget_base_total` and `budget_quote_total` and asserts they deserialize as `Decimal`.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL because the new fields do not exist yet.

**Step 3: Write minimal implementation**

Add `budget_base_total` and `budget_quote_total` to `TradingConfig` and wire them into the sample configs.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS

### Task 2: Add Effective Balance Budgeting To State

**Files:**
- Modify: `src/state.py`
- Modify: `src/models.py`
- Test: `tests/test_state.py`

**Step 1: Write the failing test**

Add state tests that:
- cap effective balances by configured budgets
- preserve the smaller of exchange balance and budget
- apply local balance deltas against effective balances

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_state.py -q`
Expected: FAIL because state does not yet track separate exchange/effective balances.

**Step 3: Write minimal implementation**

Update `BotState` to:
- store raw `exchange_balances`
- store configured budget caps
- derive effective balances from `min(exchange, budget)`
- keep `free_balance()` and `total_balance()` returning effective balances
- expose a startup validation helper for budget vs exchange totals

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_state.py -q`
Expected: PASS

### Task 3: Enforce Budget Validation During Bootstrap

**Files:**
- Modify: `src/bot.py`
- Test: `tests/test_bot.py`

**Step 1: Write the failing test**

Add a bot bootstrap test that configures a budget larger than the account balance and asserts bootstrap stops with a clear error.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bot.py -q`
Expected: FAIL because bootstrap does not validate budgets yet.

**Step 3: Write minimal implementation**

After live balances are fetched during bootstrap, validate that configured base/quote budgets do not exceed current account totals. Fail fast before trading starts when they do.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bot.py -q`
Expected: PASS

### Task 4: Make Execution And Risk Use Budgeted Balances

**Files:**
- Modify: `src/risk.py`
- Modify: `src/executor.py`
- Test: `tests/test_risk.py`
- Test: `tests/test_executor_keep_partial.py`

**Step 1: Write the failing test**

Add tests that confirm:
- bid/ask permission is blocked by the effective budgeted balance, not the full exchange balance
- max placeable size respects the budget cap

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_risk.py tests/test_executor_keep_partial.py -q`
Expected: FAIL because execution and risk still assume full balances.

**Step 3: Write minimal implementation**

Keep `risk.py` and `executor.py` on the existing `free_balance()/total_balance()` API, but ensure their results now reflect the effective budgeted balances through the state layer.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_risk.py tests/test_executor_keep_partial.py -q`
Expected: PASS

### Task 5: Verify Full Relevant Test Slice

**Files:**
- Modify: `tests/test_config.py`
- Modify: `tests/test_state.py`
- Modify: `tests/test_bot.py`
- Modify: `tests/test_risk.py`
- Modify: `tests/test_executor_keep_partial.py`

**Step 1: Run verification**

Run: `python -m pytest tests/test_config.py tests/test_state.py tests/test_bot.py tests/test_risk.py tests/test_executor_keep_partial.py -q`
Expected: PASS

**Step 2: Run broader regression**

Run: `python -m pytest tests -q`
Expected: PASS or report exact failing tests if existing unrelated issues remain.
