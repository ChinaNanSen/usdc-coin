# Binance Adapter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Binance Spot adapter with mainnet/testnet switching, REST trading, WS market data, and WS user feedback while preserving the existing OKX strategy/risk/state path.

**Architecture:** Keep OKX and Binance as parallel exchange adapters. Reuse the bot, executor, risk, state, and audit layers by routing through exchange-specific REST and stream implementations selected from config. Use Binance REST for bootstrap and order writes, and Binance WS for market data and user/order/account feedback.

**Tech Stack:** Python 3.12, `httpx`, `websockets`, HMAC SHA256 signing, pytest

---

### Task 1: Add Binance Config Surface

**Files:**
- Modify: `src/config.py`
- Modify: `config/config.example.yaml`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add config tests that load:

- `exchange.name: binance`
- `exchange.binance_env: testnet`
- Binance REST/WS defaults

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -q`
Expected: FAIL because Binance config fields do not exist yet.

**Step 3: Write minimal implementation**

Add Binance-specific config fields and runtime default resolution for mainnet/testnet URLs.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -q`
Expected: PASS

### Task 2: Add Binance Auth and REST Client

**Files:**
- Create: `src/binance_auth.py`
- Create: `src/binance_rest.py`
- Test: `tests/test_binance_rest.py`

**Step 1: Write the failing test**

Add tests for:

- signed REST headers
- exchange info parsing
- book parsing
- account balance parsing
- order placement/cancel response parsing

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_binance_rest.py -q`
Expected: FAIL because Binance adapter files do not exist yet.

**Step 3: Write minimal implementation**

Implement a Binance signer and REST client methods mirroring the existing OKX surface where possible.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_binance_rest.py -q`
Expected: PASS

### Task 3: Add Binance Public Market Data Stream

**Files:**
- Create: `src/binance_market_data.py`
- Test: `tests/test_binance_market_data.py`

**Step 1: Write the failing test**

Add tests that validate Binance WS payload parsing into:

- `BookSnapshot`
- `TradeTick`

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_binance_market_data.py -q`
Expected: FAIL because stream adapter does not exist yet.

**Step 3: Write minimal implementation**

Implement Binance public stream subscription and parsing with callbacks matching the current bot expectations.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_binance_market_data.py -q`
Expected: PASS

### Task 4: Add Binance Private User Stream

**Files:**
- Create: `src/binance_private_stream.py`
- Test: `tests/test_binance_private_stream.py`

**Step 1: Write the failing test**

Add tests for:

- listen key lifecycle logic
- order/execution event parsing
- balance event parsing

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_binance_private_stream.py -q`
Expected: FAIL because private stream adapter does not exist yet.

**Step 3: Write minimal implementation**

Implement Binance user stream client with reconnect, keepalive, and callback dispatch.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_binance_private_stream.py -q`
Expected: PASS

### Task 5: Route Bot Startup By Exchange Name

**Files:**
- Modify: `src/bot.py`
- Modify: `main.py`
- Test: `tests/test_bot.py`

**Step 1: Write the failing test**

Add bot tests that assert:

- OKX config still uses OKX clients
- Binance config selects Binance REST/public/private adapters
- Binance simulated/mainnet settings route correctly

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bot.py -q`
Expected: FAIL because bot only knows OKX classes.

**Step 3: Write minimal implementation**

Add exchange-name-based routing for REST, market data, and private user streams while keeping the existing OKX path intact.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_bot.py -q`
Expected: PASS

### Task 6: Extend Market Observer For Binance

**Files:**
- Modify: `src/market_observer.py`
- Test: `tests/test_market_observer.py`

**Step 1: Write the failing test**

Add observer tests for Binance data collection with the same report structure already used for OKX.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_market_observer.py -q`
Expected: FAIL because observer is hardwired to OKX.

**Step 3: Write minimal implementation**

Teach observer to instantiate the correct REST adapter based on config and keep the report format unchanged.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_market_observer.py -q`
Expected: PASS

### Task 7: Verify Full Test Suite

**Files:**
- Modify: relevant tests above

**Step 1: Run focused adapter tests**

Run: `python3 -m pytest tests/test_config.py tests/test_binance_rest.py tests/test_binance_market_data.py tests/test_binance_private_stream.py tests/test_bot.py tests/test_market_observer.py -q`
Expected: PASS

**Step 2: Run broader regression**

Run: `python3 -m pytest tests -q`
Expected: PASS
