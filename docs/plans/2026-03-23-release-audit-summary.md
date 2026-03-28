# Release Audit Summary Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show release-only inventory and release execution totals directly in the audit summary so users can understand release-leg progress without watching the live terminal panel.

**Architecture:** Keep `render_audit_summary()` as the single entrypoint. Extend the snapshot section to render release-only inventory accounting from state snapshot plus config, and extend the run section to aggregate release fills from `order_update` events using the existing reason/reason-bucket metadata.

**Tech Stack:** Python 3.12, Decimal, JSON, SQLite, pytest

---

### Task 1: Add release snapshot summary test

**Files:**
- Modify: `tests/test_audit_summary.py`

**Step 1: Write the failing test**

Add a test that verifies release-only snapshot text shows:

- initial external base
- remaining external base
- released amount
- release buffer
- releasable amount

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_audit_summary.py -q`
Expected: FAIL because the summary does not render release-only snapshot details yet.

**Step 3: Write minimal implementation**

Add release-only snapshot rendering in `src/audit_summary.py`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_audit_summary.py -q`
Expected: PASS

### Task 2: Add release run summary test

**Files:**
- Modify: `tests/test_audit_summary.py`
- Modify: `src/audit_summary.py`

**Step 1: Write the failing test**

Add a test that records a `release_external_long` filled order and asserts the run summary includes release fill count, base size, and quote turnover.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_audit_summary.py -q`
Expected: FAIL because run summary does not aggregate release fills yet.

**Step 3: Write minimal implementation**

Aggregate release fills inside `_render_run_section()` using `reason` / `reason_bucket`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_audit_summary.py -q`
Expected: PASS

### Task 3: Verify regressions

**Files:**
- Modify: relevant files above

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_audit_summary.py tests/test_status_panel.py -q`
Expected: PASS

**Step 2: Run full regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
