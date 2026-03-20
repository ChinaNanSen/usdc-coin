# Secondary Edge Filter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a soft positive-edge filter for secondary quotes so low-value secondary turnover is reduced without blocking primary rebalance exits.

**Architecture:** Introduce a shared passive-edge helper, wire strategy-side secondary quote filtering and second-layer gating to it, and align executor overlay preservation with the same edge definition. Update runtime config and add focused regression tests.

**Tech Stack:** Python, pytest, OKX spot market making bot

---

### Task 1: Shared Passive Edge Helper

**Files:**
- Modify: `src/utils.py`
- Test: `tests/test_strategy.py`

**Step 1: Write the failing test**

Add a strategy test that depends on a shared passive-edge interpretation for thin-edge secondary quotes.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_strategy.py -q`
Expected: FAIL on new assertions

**Step 3: Write minimal implementation**

Add a utility that computes passive edge ticks for buy/sell quotes from current best bid/ask.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_strategy.py -q`
Expected: PASS

### Task 2: Strategy Secondary Soft Filter

**Files:**
- Modify: `src/config.py`
- Modify: `config/config.yaml`
- Modify: `config/config.example.yaml`
- Modify: `src/strategy.py`
- Test: `tests/test_strategy.py`

**Step 1: Write the failing tests**

Add tests for:
- thin-edge secondary quote size reduction
- below-threshold secondary quote suppression
- stricter `join_second_*` layer gating

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_strategy.py -q`
Expected: FAIL on new assertions

**Step 3: Write minimal implementation**

Add new strategy config fields and apply them only to `rebalance_secondary_*` and `join_second_*` generation.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_strategy.py -q`
Expected: PASS

### Task 3: Executor Overlay Alignment

**Files:**
- Modify: `src/executor.py`
- Test: `tests/test_okx_rest.py`

**Step 1: Write the failing test**

Add a test where overlay preservation should fail once secondary minimum positive edge is raised above the current edge.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_okx_rest.py -q`
Expected: FAIL on preserve behavior

**Step 3: Write minimal implementation**

Update overlay preservation to use the same passive-edge definition and minimum edge threshold as secondary quote creation.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_okx_rest.py -q`
Expected: PASS

### Task 4: Full Verification

**Files:**
- Modify: `src/utils.py`
- Modify: `src/config.py`
- Modify: `config/config.yaml`
- Modify: `config/config.example.yaml`
- Modify: `src/strategy.py`
- Modify: `src/executor.py`
- Modify: `tests/test_strategy.py`
- Modify: `tests/test_okx_rest.py`

**Step 1: Run full suite**

Run: `python -m pytest tests -q`
Expected: PASS

**Step 2: Review config defaults**

Confirm the live config applies the intended stricter second-layer threshold while leaving primary rebalance paths unchanged.

**Step 3: Commit**

```bash
git add src/utils.py src/config.py config/config.yaml config/config.example.yaml src/strategy.py src/executor.py tests/test_strategy.py tests/test_okx_rest.py docs/plans/2026-03-19-secondary-edge-filter-design.md docs/plans/2026-03-19-secondary-edge-filter.md
git commit -m "feat: filter low-edge secondary quotes"
```
