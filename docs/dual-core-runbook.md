# Dual-Core Runbook

This runbook starts the `USDC-USDT` and `USDG-USDT` instances as separate bots on the same OKX account, with instance-level budget isolation enabled.

## Files

- `config/config.usdc.yaml`
- `config/config.usdg.yaml`
- `config/config.observe.yaml`
- `scripts/run_dual_core.sh`

## Before You Start

1. Put credentials in `config/secret.yaml`.
2. Make sure both instance budgets fit inside the account's current balances.
3. Keep `DAI-USDT` and `PYUSD-USDT` in observe-only mode until fee and depth checks improve.

## Budget Model

Each instance now uses:

- real exchange balances as an upper bound
- per-instance configured budgets as its own local cap

The bot only trades with the smaller of those two balance views. If the configured budget exceeds the account balance at startup, the instance refuses to start.

## Recommended First Start

1. Observe markets only:

```bash
python3 main.py --config config/config.observe.yaml --observe-markets --observe-quote-size 5000
```

2. Start `USDC-USDT`:

```bash
python3 main.py --config config/config.usdc.yaml
```

3. Start `USDG-USDT`:

```bash
python3 main.py --config config/config.usdg.yaml
```

Or start both with:

```bash
bash scripts/run_dual_core.sh
```

If you are using Git Bash on Windows and `python3` is not on PATH, the script now auto-detects interpreters in this order:

- `PYTHON_BIN` if you set it manually
- `python3`
- `py -3`
- `python`

You can still force one explicitly, for example:

```bash
PYTHON_BIN=python bash scripts/run_dual_core.sh
```

## Current Defaults

`config/config.usdc.yaml`

- market: `USDC-USDT`
- budget: `12000 USDC / 12000 USDT`
- quote size: `3000 U`

`config/config.usdg.yaml`

- market: `USDG-USDT`
- budget: `8000 USDG / 8000 USDT`
- quote size: `1500 U`

## Logs And State

USDC instance writes to:

- `trend_bot_6/data/usdc/journal.sim.jsonl`
- `trend_bot_6/data/usdc/audit.sim.db`
- `trend_bot_6/data/usdc/state_snapshot.sim.json`

USDG instance writes to:

- `trend_bot_6/data/usdg/journal.sim.jsonl`
- `trend_bot_6/data/usdg/audit.sim.db`
- `trend_bot_6/data/usdg/state_snapshot.sim.json`

Observer writes to:

- `trend_bot_6/data/observer/journal.sim.jsonl`
- `trend_bot_6/data/observer/audit.sim.db`
- `trend_bot_6/data/observer/state_snapshot.sim.json`

## Safety Notes

- Same-account dual live is only safe now because each instance is budget-capped.
- Private order updates for other instruments are ignored by each bot instance.
- If one market loses zero-fee status, the runtime fee gate will stop that instance.
