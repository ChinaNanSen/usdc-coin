# Binance Adapter Design

**Context**

`trend_bot_6` currently has a mature OKX-centric execution path:

- REST for bootstrap and fallback trading
- WS for public market data
- WS for private user/order feedback
- exchange-specific auth, routing, and environment handling

The new goal is to add a Binance Spot adapter with:

- `mainnet` / `testnet` switch
- public market data
- private user stream
- account / open orders bootstrap
- order place / cancel / query support
- terminal output and audit logging behavior comparable to OKX

**Recommendation**

Use a Binance-specific adapter layer instead of a full exchange-agnostic refactor.

Why:

- The current codebase is still strongly shaped around OKX semantics.
- A full abstraction layer would create a large moving refactor across bot, executor, streams, auth, and tests.
- A parallel Binance implementation lets us reuse strategy, state, risk, audit, and status rendering with limited surface-area changes.

**Chosen interface split**

- Market data: use Binance WS
- User/order/account feedback: use Binance WS User Data Stream
- Bootstrap snapshots: use Binance REST
- Trading writes: use Binance REST first

This intentionally mirrors the stable OKX path:

- fast streams where low latency matters
- REST for deterministic startup and trade write control

Binance also exposes trading-capable WebSocket APIs, but first delivery should prioritize behavior parity and debuggability over transport symmetry.

**Files to add**

- `src/binance_auth.py`
- `src/binance_rest.py`
- `src/binance_market_data.py`
- `src/binance_private_stream.py`

**Files to modify**

- `src/config.py`
- `src/bot.py`
- `src/market_observer.py`
- `main.py`
- tests covering config, Binance REST, Binance streams, and exchange routing

**Environment model**

Add exchange selection and environment selection:

- `exchange.name`: `okx | binance`
- `exchange.binance_env`: `mainnet | testnet`

Binance base URLs should be resolved from this config:

- mainnet REST: `https://api.binance.com`
- mainnet public market-data alternative: `https://data-api.binance.vision` for public-only reads where useful
- testnet REST: `https://testnet.binance.vision/api`
- mainnet public WS / user WS: Binance Spot WS endpoints
- testnet public WS / user WS: Binance Spot Testnet WS endpoints

**Minimal Binance feature parity**

Public:

- exchange info
- order book
- best bid/ask ticker
- 24h ticker

Private:

- account balances
- open orders
- new order
- cancel order
- order status / query
- user stream execution and balance updates

**Non-goals for first Binance delivery**

- unified exchange abstraction framework
- advanced Binance WS trading writes
- margin / futures / funding / transfer support
- multi-symbol Binance controller

**Known risk**

Mainnet Binance public API access has already been verified from the current network egress, but private signed trading endpoints still need live key validation during implementation. Testnet support should be implemented in parallel to keep the adapter testable without risking mainnet writes.
