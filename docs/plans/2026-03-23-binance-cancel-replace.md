# Binance CancelReplace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Binance Spot `cancelReplace` support to the existing amend path so Binance orders can be repriced through the unified executor without forcing immediate cancel-and-replace fallback.

**Architecture:** Keep the executor's single `amend_order` entrypoint. Implement Binance-specific `amend_order()` in `src/binance_rest.py` using `POST /api/v3/order/cancelReplace`, then bridge the "old order replaced by new order" semantics inside the executor/state path so local order tracking stays consistent until private stream confirmation arrives.

**Tech Stack:** Python 3.12, `httpx`, Decimal, pytest

---

### Task 1: Add Binance cancelReplace REST coverage

**Files:**
- Modify: `src/binance_rest.py`
- Modify: `tests/test_binance_rest.py`

**Step 1: Write the failing test**

Add REST tests that verify:

- `amend_order()` sends `POST /api/v3/order/cancelReplace`
- success returns the new order identifiers from `newOrderResponse`
- partial/full failures raise `BinanceAPIError`

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_binance_rest.py -q`
Expected: FAIL because `amend_order()` does not exist yet.

**Step 3: Write minimal implementation**

Implement `BinanceRestClient.amend_order()` with:

- `cancelReplaceMode=STOP_ON_FAILURE`
- `newOrderRespType=RESULT`
- `LIMIT_MAKER` when `post_only=True`
- `orderId` first, `origClientOrderId` fallback

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_binance_rest.py -q`
Expected: PASS

### Task 2: Bridge Binance replacement semantics in executor

**Files:**
- Modify: `src/executor.py`
- Modify: `tests/test_okx_rest.py`

**Step 1: Write the failing test**

Add executor tests that verify:

- when Binance amend returns a new `clOrdId`, local live order tracking switches from old order to new order
- pending amend identity also switches to the new order
- amend failure still falls back to cancel

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_okx_rest.py -q`
Expected: FAIL because executor still assumes amend keeps the same local order identity.

**Step 3: Write minimal implementation**

After amend success, if response carries a different `ordId` or `clOrdId`:

- move pending amend identity
- remove the old live order shadow
- insert a replacement live order using the target price/size
- keep pending amend open until later order feedback confirms it

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_okx_rest.py -q`
Expected: PASS

### Task 3: Verify regressions

**Files:**
- Modify: relevant tests above

**Step 1: Run focused verification**

Run: `python3 -m pytest tests/test_binance_rest.py tests/test_okx_rest.py -q`
Expected: PASS

**Step 2: Run broader exchange regression**

Run: `python3 -m pytest tests/test_bot.py tests/test_binance_private_stream.py tests/test_executor_keep_partial.py -q`
Expected: PASS

**Step 3: Run full suite**

Run: `python3 -m pytest tests -q`
Expected: PASS
