# Triangle Route Diagnostics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Binance triangle routing observable and explainable before any threshold tuning.

**Architecture:** Add a small diagnostics object to bot state, refresh it each loop from the current triangle snapshot and current book, journal only on change, and surface it in the terminal panel plus the existing route-chain report.

**Tech Stack:** Python 3.12, Decimal, JSONL journal, pytest

---

### Task 1: Add route diagnostics state and persistence

**Files:**
- Modify: `src/state.py`
- Test: `tests/test_state.py`

**Step 1: Add state field**

Store a `triangle_route_diagnostics` dict on `BotState`.

**Step 2: Persist and restore**

Include the field in state snapshot save/load.

**Step 3: Verify**

Run: `python3 -m pytest tests/test_state.py -q`

### Task 2: Compute diagnostics in bot

**Files:**
- Modify: `src/bot.py`
- Modify: `src/triangle_routing.py`
- Test: `tests/test_bot.py`

**Step 1: Build diagnostics payload**

Include:

- snapshot status
- snapshot age
- position base
- route choice status
- entry buy gate status
- direct / indirect dual-exit edge metrics if available

**Step 2: Journal only on change**

Emit a `triangle_route_diagnostics` event only when the payload changes.

**Step 3: Verify**

Run: `python3 -m pytest tests/test_bot.py -q`

### Task 3: Surface diagnostics in terminal and report

**Files:**
- Modify: `src/status_panel.py`
- Modify: `src/binance_route_chain_report.py`
- Test: `tests/test_status_panel.py`
- Test: `tests/test_binance_route_chain_report.py`

**Step 1: Show diagnostics in terminal**

When triangle routing is enabled, show a route line even if there is no current route choice.

**Step 2: Extend route-chain report**

Show latest diagnostics and route status even when fills are absent.

**Step 3: Verify**

Run: `python3 -m pytest tests/test_status_panel.py tests/test_binance_route_chain_report.py -q`

### Task 4: Full regression

**Files:**
- Modify: relevant files above

**Step 1: Run focused suite**

Run: `python3 -m pytest tests/test_bot.py tests/test_state.py tests/test_status_panel.py tests/test_binance_route_chain_report.py -q`

**Step 2: Run full suite**

Run: `python3 -m pytest tests -q`
