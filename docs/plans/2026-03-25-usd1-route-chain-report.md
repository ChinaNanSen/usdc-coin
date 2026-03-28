# USD1 Route Chain Report Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dedicated report for the `USD1-USDT` main leg plus `USD1-USDC` release leg so the current route-chain effect on inventory, release activity, and realized profit can be checked from one command.

**Architecture:** Keep the report separate from the bot. Reuse state snapshots, the shared route ledger, and `analyze_reason_attribution()` to build a single text report covering current state plus the latest filled runs for the main leg and release leg.

**Tech Stack:** Python 3.12, JSON, Decimal, pytest

---

### Task 1: Add report tests

**Files:**
- Create: `tests/test_binance_route_chain_report.py`
- Create: `src/binance_route_chain_report.py`

**Step 1: Write the failing test**

Add a test that creates:

- a main-leg state snapshot
- a release-leg state snapshot
- a shared route ledger file
- tiny journals for both legs

and asserts the report contains:

- main leg state
- release leg state
- route ledger totals
- attribution snippets

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_binance_route_chain_report.py -q`
Expected: FAIL because the report module does not exist yet.

**Step 3: Write minimal implementation**

Implement the report builder using:

- snapshot JSON
- `analyze_reason_attribution()`
- route ledger aggregation

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_binance_route_chain_report.py -q`
Expected: PASS

### Task 2: Add CLI wrapper

**Files:**
- Create: `scripts/binance_route_chain_report.py`

**Step 1: Add CLI**

Add a small wrapper that accepts:

- main state/journal
- release state/journal
- route ledger path

and prints the report.

**Step 2: Run smoke test**

Run the script on synthetic test fixtures or current real files.

### Task 3: Verify regressions

**Files:**
- Modify: relevant files above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_binance_route_chain_report.py tests/test_order_reason_attribution.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
