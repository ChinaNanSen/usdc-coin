# Release Leg Idle-Start Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow the `USD1-USDC` release-only leg to start and idle safely even when current balances are below configured budgets, and make the Binance stable-core launcher start that release leg by default.

**Architecture:** Keep the existing startup budget gate for normal instances, but bypass it for `release_only_mode` because the strategy itself now prevents quoting until releasable external inventory exists. Update the Binance stable-core script so the release leg starts by default and relies on runtime idling instead of manual delayed startup.

**Tech Stack:** Python 3.12, Bash, pytest

---

### Task 1: Add release-only budget gate test

**Files:**
- Modify: `tests/test_bot.py`

**Step 1: Write the failing test**

Add a test that verifies:

- release-only bot with configured budget above current exchange balances is still allowed to start through `_check_live_budget_gate()`

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bot.py -q`
Expected: FAIL because budget gate still blocks all live instances equally.

**Step 3: Write minimal implementation**

Make `_check_live_budget_gate()` bypass the block when `config.strategy.release_only_mode` is true, and emit a journal event documenting that bypass.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bot.py -q`
Expected: PASS

### Task 2: Start release leg by default in stable-core launcher

**Files:**
- Modify: `scripts/run_binance_stable_core.sh`

**Step 1: Update launcher defaults**

Make `START_USD1_USDC` default to `1` and adjust the output text so users can still disable it explicitly.

**Step 2: Run shell syntax check**

Run: `bash -n scripts/run_binance_stable_core.sh`
Expected: PASS

### Task 3: Verify regressions

**Files:**
- Modify: relevant tests above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_bot.py tests/test_strategy.py tests/test_state.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
