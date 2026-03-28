# Release Status Panel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show release-only runtime status directly in the terminal panel so users can see remaining external inventory, release buffer, releasable size, and whether the release leg is currently active or idle.

**Architecture:** Keep the existing terminal panel layout. Pass the release-only config flags into `TerminalStatusPanel`, then add a single release status line that derives its values from the bot state and current decision without changing any strategy or risk behavior.

**Tech Stack:** Python 3.12, Decimal, pytest

---

### Task 1: Add release panel test

**Files:**
- Modify: `tests/test_status_panel.py`

**Step 1: Write the failing test**

Add a test that verifies a release-only state renders:

- `释放 |`
- `模式=是`
- remaining external inventory
- release buffer
- releasable size
- current action text

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_status_panel.py -q`
Expected: FAIL because the panel does not render release status yet.

**Step 3: Write minimal implementation**

Pass release-only config into the panel and add the single release status line.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_status_panel.py -q`
Expected: PASS

### Task 2: Wire panel config from bot

**Files:**
- Modify: `src/bot.py`
- Modify: `src/status_panel.py`

**Step 1: Add panel constructor fields**

Pass:

- `release_only_mode`
- `release_only_base_buffer`

from bot config into the status panel.

**Step 2: Verify no behavior change for normal bots**

Run: `python3 -m pytest tests/test_status_panel.py tests/test_bot.py -q`
Expected: PASS

### Task 3: Run full regression

**Files:**
- Modify: relevant files above

**Step 1: Run full suite**

Run: `python3 -m pytest tests -q`
Expected: PASS
