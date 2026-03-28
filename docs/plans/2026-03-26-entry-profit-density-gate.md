# Entry Profit Density Gate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce low-value entry churn by scaling down new entry size when recent entry-side realized profit per 10k turnover is weak.

**Architecture:** Add a lightweight rolling entry-profit-density signal to bot state, refresh it from recent journal data in the bot, and apply the resulting size factor only to entry intents in strategy. Keep rebalance and release logic untouched.

**Tech Stack:** Python 3.12, Decimal, JSONL parsing, pytest

---

### Task 1: Add strategy gate tests

**Files:**
- Modify: `tests/test_strategy.py`

**Step 1: Write the failing test**

Add tests that verify:

- weak entry profit density scales down entry size
- strong entry profit density leaves entry size unchanged

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: FAIL because strategy ignores entry profit density.

**Step 3: Write minimal implementation**

Add entry-profit-density config and scale factor logic in strategy.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: PASS

### Task 2: Add state/bot signal plumbing

**Files:**
- Modify: `src/config.py`
- Modify: `src/state.py`
- Modify: `src/bot.py`

**Step 1: Add config and state fields**

Store:

- recent entry per10k
- recent entry size factor

**Step 2: Refresh signal in bot**

Periodically parse recent journal window and compute entry-only realized/turnover per10k.

### Task 3: Verify regressions

**Files:**
- Modify: relevant files above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_strategy.py tests/test_bot.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
