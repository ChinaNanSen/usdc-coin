# AGENTS.md

## Overview

This repository is a spot/stable-market trading bot with Binance and OKX related code.
Protect runtime stability, accounting consistency, and route/risk logic first.

## Runtime

- Preferred Python on this machine:
  - `C:\\Users\\Nan\\AppData\\Local\\Programs\\Python\\Python312\\python.exe`
- Main entry:
  - `main.py`
- Important directories:
  - `src/`
  - `config/`
  - `tests/`
  - `data/`
  - `logs/`

## Safety

- Do not delete or reset state under `data/`.
- Do not overwrite exchange secrets.
- Do not change route/risk logic without targeted tests.
- Preserve journal/state compatibility when modifying bot state or accounting fields.

## Trading-Specific Rules

- Optimize for:
  - net profitability
  - route quality
  - consistency of state and fills
- When analyzing strategy changes, distinguish:
  - route-selection logic
  - execution / amend behavior
  - inventory / release logic

## Validation

- Run focused tests before broader suites.
- Prefer:
  - `python.exe -m pytest tests/<target> -q`
  - `python.exe -m py_compile ...`
- Avoid touching unrelated configs or logs.

## ECC-Derived Python Rules

- Prefer `pytest` for all new regression coverage.
- For new or modified public helpers, prefer explicit type annotations when they fit the surrounding file style.
- Validate external data at boundaries:
  - exchange REST responses
  - websocket payloads
  - journal/state snapshot content
  - route-ledger events
- Prefer small focused helpers over extending already-large bot methods further.
- Use context managers for file access and state/report readers.
- Prefer incremental parsing for large JSONL journals and state files.
- Do not introduce formatter/linter dependencies just because ECC recommends them.
- Prefer copy-on-write or normalized payload transforms when handling exchange state, but do not rewrite stable code purely for style.

## ECC-Derived Workflow

- Research before implementation:
  - inspect `state_snapshot*.json`
  - inspect `journal*.jsonl`
  - inspect existing tests first
  - inspect config variants before changing defaults
- For strategy work, distinguish:
  - route quality
  - execution/amend quality
  - inventory efficiency
  - accounting consistency

## ECC-Derived Security

- Keep secrets in environment variables or secret YAML files already used by the repo.
- Never hardcode exchange keys, proxy credentials, tokens, or webhook URLs.
- Avoid logging authenticated request secrets or full credential-bearing configs.
- If doing a broader security pass, `bandit -r src/` is a reasonable optional tool, but do not make it mandatory for normal edits.

## Codex Usage

- Use this file as the main instruction layer for Codex.
- Project-local Codex defaults live in `.codex/config.toml`.
- Keep configuration conservative and compatible with local development.
