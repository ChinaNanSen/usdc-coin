from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ExchangeConfig:
    rest_url: str = "https://www.okx.com"
    public_ws_url: str = "wss://ws.okx.com:8443/ws/v5/public"
    private_ws_url: str = "wss://ws.okx.com:8443/ws/v5/private"
    api_key: str = ""
    secret_key: str = ""
    passphrase: str = ""
    simulated: bool = False
    request_timeout_seconds: float = 10.0
    user_agent: str = "trend_bot_6/0.1"

    def apply_env(self) -> None:
        self.api_key = self.api_key or os.getenv("OKX_API_KEY", "")
        self.secret_key = self.secret_key or os.getenv("OKX_SECRET_KEY", "")
        self.passphrase = self.passphrase or os.getenv("OKX_PASSPHRASE", "")

    def apply_runtime_defaults(self) -> None:
        if not self.simulated:
            return

        ws_mapping = {
            "wss://ws.okx.com:8443/ws/v5/public": "wss://wspap.okx.com:8443/ws/v5/public",
            "wss://ws.okx.com:8443/ws/v5/private": "wss://wspap.okx.com:8443/ws/v5/private",
            "wss://wsus.okx.com:8443/ws/v5/public": "wss://wsuspap.okx.com:8443/ws/v5/public",
            "wss://wsus.okx.com:8443/ws/v5/private": "wss://wsuspap.okx.com:8443/ws/v5/private",
        }
        self.public_ws_url = ws_mapping.get(self.public_ws_url, self.public_ws_url)
        self.private_ws_url = ws_mapping.get(self.private_ws_url, self.private_ws_url)


@dataclass
class TradingConfig:
    inst_id: str = "USDC-USDT"
    inst_type: str = "SPOT"
    base_ccy: str = "USDC"
    quote_ccy: str = "USDT"
    entry_base_size: Decimal = Decimal("0")
    post_only: bool = False
    quote_size: Decimal = Decimal("10000")
    min_quote_size: Decimal = Decimal("1000")
    max_quote_size: Decimal = Decimal("10000")
    loop_interval_seconds: float = 1.0
    balance_poll_interval_seconds: float = 10.0
    order_ttl_seconds: float = 8.0
    cancel_on_ttl_expiry: bool = False
    action_cooldown_seconds: float = 1.0
    bootstrap_depth: int = 5
    shadow_base_balance: Decimal = Decimal("50000")
    shadow_quote_balance: Decimal = Decimal("50000")


@dataclass
class StrategyConfig:
    min_spread_ticks: int = 1
    inventory_target_pct: Decimal = Decimal("0.50")
    inventory_soft_lower_pct: Decimal = Decimal("0.45")
    inventory_soft_upper_pct: Decimal = Decimal("0.55")
    mild_skew_threshold_pct: Decimal = Decimal("0.03")
    mild_skew_size_factor: Decimal = Decimal("0.50")
    visible_depth_levels: int = 5
    min_visible_depth_multiplier: Decimal = Decimal("3")
    rebalance_min_profit_ticks: int = 1
    normal_sell_price_floor: Decimal = Decimal("0")
    preserve_entry_queue: bool = True
    preserve_rebalance_queue: bool = True


@dataclass
class RiskConfig:
    stale_book_ms: int = 15000
    cancel_orders_on_stale_book: bool = False
    max_reconnects_per_5m: int = 3
    daily_loss_limit_quote: Decimal = Decimal("50")
    min_free_quote_buffer: Decimal = Decimal("1000")
    min_free_base_buffer: Decimal = Decimal("1000")
    fail_on_foreign_pending_orders: bool = True
    cancel_managed_orders_on_startup: bool = True
    cancel_managed_orders_on_shutdown: bool = True
    cancel_managed_orders_on_public_reconnect: bool = False
    allow_emergency_ioc: bool = False
    hard_inventory_lower_pct: Decimal = Decimal("0.35")
    hard_inventory_upper_pct: Decimal = Decimal("0.65")
    pause_after_reconnect_seconds: float = 5.0
    max_mid_deviation_bps: Decimal = Decimal("20")
    peg_reference_price: Decimal = Decimal("1")
    max_consecutive_place_failures: int = 3
    max_consecutive_cancel_failures: int = 3
    place_failure_cooldown_seconds: float = 30.0
    cancel_failure_cooldown_seconds: float = 30.0
    instrument_poll_interval_seconds: float = 300.0
    fee_poll_interval_seconds: float = 300.0
    require_public_stream_ready: bool = True
    require_private_stream_ready: bool = True
    enforce_effective_fee_gate: bool = True
    max_effective_maker_fee_rate: Decimal = Decimal("0")
    max_effective_taker_fee_rate: Decimal = Decimal("0")
    zero_fee_instruments: list[str] = field(default_factory=lambda: ["USDC-USDT"])
    max_managed_orders_per_side: int = 1
    max_consistency_failures: int = 3
    cancel_managed_on_consistency_failure: bool = False
    balance_consistency_tolerance_quote: Decimal = Decimal("1")
    require_passive_prices_on_resync: bool = True


@dataclass
class ShadowConfig:
    subscribe_trades: bool = True
    min_rest_seconds: float = 1.0
    queue_ahead_fraction: Decimal = Decimal("1")
    update_queue_from_books: bool = True
    fill_on_book_cross: bool = True


@dataclass
class TelemetryConfig:
    journal_path: str = "data/journal.jsonl"
    sqlite_enabled: bool = True
    sqlite_path: str = "data/audit.db"
    state_path: str = "data/state_snapshot.json"
    snapshot_interval_seconds: float = 30.0
    status_panel_enabled: bool = True
    status_panel_interval_seconds: float = 1.0
    status_panel_clear_screen: bool = True
    status_panel_render_non_interactive: bool = False


@dataclass
class BotConfig:
    mode: str = "shadow"
    managed_prefix: str = "bot6"
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    shadow: ShadowConfig = field(default_factory=ShadowConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)


def _merge_dataclass(obj: Any, data: dict[str, Any]) -> Any:
    for key, value in data.items():
        if not hasattr(obj, key):
            continue
        current = getattr(obj, key)
        if isinstance(current, Decimal):
            setattr(obj, key, Decimal(str(value)))
        else:
            setattr(obj, key, value)
    return obj


def _resolve_runtime_path(raw_path: str, *, config_path: Path) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)

    project_root = config_path.parent.parent
    workspace_root = project_root.parent
    preferred = workspace_root / path if path.parts and path.parts[0] == project_root.name else project_root / path

    candidates = [
        Path.cwd() / path,
        config_path.parent / path,
        project_root / path,
        workspace_root / path,
    ]
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return str(candidate)
    return str(preferred)


def load_config(
    path: str | os.PathLike[str],
    mode_override: str | None = None,
    *,
    validate_live_credentials: bool = True,
) -> BotConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = BotConfig()
    config.mode = mode_override or raw.get("mode", config.mode)

    _merge_dataclass(config.exchange, raw.get("exchange", {}))
    _merge_dataclass(config.trading, raw.get("trading", {}))
    _merge_dataclass(config.strategy, raw.get("strategy", {}))
    _merge_dataclass(config.risk, raw.get("risk", {}))
    _merge_dataclass(config.shadow, raw.get("shadow", {}))
    _merge_dataclass(config.telemetry, raw.get("telemetry", {}))
    config.telemetry.journal_path = _resolve_runtime_path(config.telemetry.journal_path, config_path=config_path)
    config.telemetry.sqlite_path = _resolve_runtime_path(config.telemetry.sqlite_path, config_path=config_path)
    config.telemetry.state_path = _resolve_runtime_path(config.telemetry.state_path, config_path=config_path)

    config.exchange.apply_env()
    config.exchange.apply_runtime_defaults()
    if config.mode == "live" and validate_live_credentials:
        missing = [
            name
            for name, value in {
                "OKX_API_KEY": config.exchange.api_key,
                "OKX_SECRET_KEY": config.exchange.secret_key,
                "OKX_PASSPHRASE": config.exchange.passphrase,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"Live mode requires credentials: {', '.join(missing)}")
    return config
