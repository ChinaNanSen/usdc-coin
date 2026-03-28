# Rebalance Profit Guard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent low-quality rebalance fills from damaging profitability by scaling down rebalance size and increasing minimum required profit ticks when recent rebalance profit density is weak.

**Architecture:** Mirror the new entry profit-density signal path. Compute a rolling rebalance-only per10k signal in bot, store a rebalance size factor plus extra required ticks in state, and apply both to rebalance target construction in strategy.

**Tech Stack:** Python 3.12, Decimal, JSONL parsing, pytest

---

### Task 1: Add rebalance protection tests

**Files:**
- Modify: `tests/test_strategy.py`

**Step 1: Write the failing test**

Add tests that verify:

- weak rebalance profit density shrinks rebalance size
- weak rebalance profit density increases rebalance profit ticks

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: FAIL because strategy ignores rebalance profit density.

**Step 3: Write minimal implementation**

Add config/state fields and apply rebalance size/tick penalties in strategy.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_strategy.py -q`
Expected: PASS

### Task 2: Add bot signal refresh

**Files:**
- Modify: `src/config.py`
- Modify: `src/state.py`
- Modify: `src/bot.py`
- Modify: `tests/test_bot.py`

**Step 1: Add signal fields**

Store:

- `rebalance_profit_density_per10k`
- `rebalance_profit_density_size_factor`
- `rebalance_profit_density_extra_ticks`

**Step 2: Refresh from recent journal**

Compute recent `rebalance` realized/turnover and derive state penalties.

### Task 3: Verify regressions

**Files:**
- Modify: relevant files above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_strategy.py tests/test_bot.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
