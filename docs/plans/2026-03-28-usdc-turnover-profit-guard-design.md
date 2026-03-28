# USDC Turnover Profit Guard Design

## Goal

Improve capital turnover and realized profitability for the OKX `USDC-USDT` bot by reducing long-inventory lockups without introducing aggressive taker logic.

## Scope

This design only covers two behavioral changes:

1. Add a long-inventory sell-drought guard that suppresses new entry buys when the bot is already long and rebalance sells have gone quiet for too long.
2. Add a rebalance amend fallback so failed rebalance reprices can degrade to cancel-and-replace instead of leaving stale release orders stuck on the book.

This design does not add IOC logic, taker logic, route changes, or new alpha signals.

## Current Problem

Recent OKX simulated runs show three repeated patterns:

- The bot spends most of its time outside normal two-sided quoting and flips between `REDUCE_ONLY` and `PAUSED`.
- Entry buys keep adding long inventory faster than rebalance sells can release it.
- Rebalance sell orders frequently fail to amend, then remain at stale prices and keep capital trapped.

The result is positive but thin PnL with poor capital turnover.

## Design

### 1. Sell-Drought Guard

The strategy should stop opening new entry buys before the hard inventory cap is breached.

The new guard will only apply when all conditions are true:

- The bot has positive strategy inventory.
- Account inventory ratio is above a configurable soft threshold.
- There is active sell-side rebalance inventory to release.
- The most recent rebalance sell fill is older than a configurable drought window.

When active, the guard only suppresses new entry buy intents. It must not block:

- rebalance sells
- rebalance buys that repair a short inventory state
- existing order preservation logic

The decision reason should be explicit so the effect is visible in telemetry.

### 2. Rebalance Amend Fallback

When a rebalance order amend fails, the executor currently logs the error and leaves the stale order in place.

The new behavior will keep the current logging, then allow the reconcile loop to degrade as follows for rebalance intents:

- if amend succeeds: keep current behavior
- if amend fails for a rebalance order: immediately attempt `cancel_order(..., reason=\"reprice_or_ttl\")`
- on the next reconcile tick, place the updated rebalance order at the new target price

This keeps the implementation simple and avoids hidden synchronous cancel-replace inside the amend path.

The fallback will be limited to rebalance reasons:

- `rebalance_open_long`
- `rebalance_open_short`
- optionally secondary rebalance layers if they hit the same amend path

Entry orders keep the current behavior.

## Data Model Changes

`BotState` needs lightweight tracking for the latest managed fill timestamp by:

- side
- reason bucket

This lets strategy logic ask a direct question:

`how long has it been since the last rebalance sell fill?`

The timestamps should be restored from snapshot state when available so a restart does not immediately clear drought history.

## Config Changes

Add new strategy config knobs with conservative defaults:

- `sell_drought_guard_enabled`
- `sell_drought_inventory_ratio_pct`
- `sell_drought_rebalance_window_seconds`

These defaults should be disabled globally in the dataclass and enabled in `config/config.usdc.yaml` only.

## Telemetry

The new behavior should surface clearly in logs and state:

- decision reason when entry buys are suppressed by drought guard
- persisted last rebalance sell fill timestamp
- existing amend error journaling remains unchanged

## Testing

Add targeted regression coverage for:

- strategy suppresses `join_best_bid` under long-inventory sell drought
- strategy still allows sell-side rebalance when drought guard is active
- non-drought scenarios keep existing entry behavior
- executor rebalance amend failure falls through to cancel path and does not silently preserve the stale order

## Risks

Main risk:

- The drought guard may reduce profitable buy-side turnover too early.

Mitigation:

- Start with a high threshold and a long drought window.
- Keep the guard limited to positive inventory and sell-side rebalance pressure.

Secondary risk:

- Cancel-and-replace fallback may reduce queue priority.

Mitigation:

- Only apply after amend failure, which already indicates the current queue state is no longer actionable.
