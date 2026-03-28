from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ExchangeConfig:
    name: str = "okx"
    rest_url: str = "https://www.okx.com"
    public_ws_url: str = "wss://ws.okx.com:8443/ws/v5/public"
    private_ws_url: str = "wss://ws.okx.com:8443/ws/v5/private"
    api_key: str = ""
    secret_key: str = ""
    passphrase: str = ""
    simulated: bool = False
    binance_env: str = "mainnet"
    request_timeout_seconds: float = 10.0
    user_agent: str = "trend_bot_6/0.1"

    def apply_env(self) -> None:
        if self.name == "binance":
            self.api_key = self.api_key or os.getenv("BINANCE_API_KEY", "")
            self.secret_key = self.secret_key or os.getenv("BINANCE_SECRET_KEY", "")
            return
        self.api_key = self.api_key or os.getenv("OKX_API_KEY", "")
        self.secret_key = self.secret_key or os.getenv("OKX_SECRET_KEY", "")
        self.passphrase = self.passphrase or os.getenv("OKX_PASSPHRASE", "")

    def apply_runtime_defaults(self) -> None:
        if self.name == "binance":
            self._apply_binance_runtime_defaults()
            return
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

    def _apply_binance_runtime_defaults(self) -> None:
        if self.binance_env == "testnet":
            self.rest_url = "https://testnet.binance.vision"
            self.public_ws_url = "wss://stream.testnet.binance.vision/ws"
            self.private_ws_url = "wss://ws-api.testnet.binance.vision/ws-api/v3"
            return
        self.rest_url = "https://api.binance.com"
        self.public_ws_url = "wss://stream.binance.com:9443/ws"
        self.private_ws_url = "wss://ws-api.binance.com:443/ws-api/v3"


@dataclass
class TradingConfig:
    inst_id: str = "USDC-USDT"
    inst_type: str = "SPOT"
    base_ccy: str = "USDC"
    quote_ccy: str = "USDT"
    budget_base_total: Decimal = Decimal("0")
    budget_quote_total: Decimal = Decimal("0")
    entry_base_size: Decimal = Decimal("0")
    post_only: bool = False
    quote_size: Decimal = Decimal("10000")
    min_quote_size: Decimal = Decimal("1000")
    max_quote_size: Decimal = Decimal("10000")
    loop_interval_seconds: float = 1.0
    balance_poll_interval_seconds: float = 10.0
    order_ttl_seconds: float = 8.0
    cancel_on_ttl_expiry: bool = False
    action_cooldown_seconds: float = 0.2
    same_price_amend_min_remaining_change_ratio: Decimal = Decimal("0.10")
    same_price_amend_min_remaining_change_base: Decimal = Decimal("250")
    event_driven_requote: bool = True
    book_requote_debounce_ms: int = 150
    bootstrap_depth: int = 5
    shadow_base_balance: Decimal = Decimal("50000")
    shadow_quote_balance: Decimal = Decimal("50000")


@dataclass
class StrategyConfig:
    min_spread_ticks: int = 1
    strict_alternating_sides: bool = False
    inventory_target_pct: Decimal = Decimal("0.50")
    inventory_soft_lower_pct: Decimal = Decimal("0.45")
    inventory_soft_upper_pct: Decimal = Decimal("0.55")
    release_only_mode: bool = False
    release_only_base_buffer: Decimal = Decimal("0")
    release_only_shared_state_paths: list[str] = field(default_factory=list)
    release_only_shared_inventory_min_base: Decimal = Decimal("100")
    release_only_shared_inventory_min_improvement_bp: Decimal = Decimal("0.20")
    triangle_routing_enabled: bool = False
    triangle_route_refresh_interval_seconds: float = 5.0
    triangle_snapshot_stale_ms: int = 15000
    triangle_strict_dual_exit_edge_bp: Decimal = Decimal("0.15")
    triangle_best_exit_edge_bp: Decimal = Decimal("0.75")
    triangle_max_worst_exit_loss_bp: Decimal = Decimal("1.25")
    triangle_indirect_leg_penalty_bp: Decimal = Decimal("0.20")
    triangle_prefer_indirect_min_improvement_bp: Decimal = Decimal("0.10")
    triangle_indirect_handoff_enabled: bool = False
    triangle_direct_sell_floor_enabled: bool = False
    triangle_direct_buy_ceiling_enabled: bool = False
    account_inventory_skew_enabled: bool = False
    mild_skew_threshold_pct: Decimal = Decimal("0.03")
    mild_skew_size_factor: Decimal = Decimal("0.50")
    visible_depth_levels: int = 5
    min_visible_depth_multiplier: Decimal = Decimal("3")
    rebalance_min_profit_ticks: int = 1
    rebalance_reload_timeout_seconds: float = 180.0
    rebalance_drift_ticks: int = 2
    rebalance_max_order_age_seconds: float = 12.0
    rebalance_release_size_factor: Decimal = Decimal("0.50")
    rebalance_release_excess_only: bool = True
    rebalance_release_max_negative_ticks: int = 1
    rebalance_release_depth_levels: int = 1
    rebalance_release_depth_fraction: Decimal = Decimal("0.10")
    rebalance_release_depth_step_bonus: Decimal = Decimal("0.05")
    secondary_layers_enabled: bool = True
    rebalance_secondary_size_factor: Decimal = Decimal("0.10")
    rebalance_overlay_floor_factor: Decimal = Decimal("0.10")
    rebalance_overlay_preserve_tolerance_ticks: int = 1
    secondary_min_positive_edge_ticks: int = 1
    secondary_full_size_edge_ticks: int = 2
    secondary_thin_edge_size_factor: Decimal = Decimal("0.10")
    secondary_entry_layer_min_edge_ticks: int = 2
    rebalance_secondary_price_offset_ticks: int = 1
    toxic_flow_min_observation_ms: int = 300
    toxic_flow_max_observation_ms: int = 1000
    toxic_flow_adverse_ticks: int = 1
    toxic_flow_cooldown_seconds: float = 2.0
    secondary_markout_window_ms: int = 1000
    secondary_markout_trigger_samples: int = 3
    secondary_markout_adverse_threshold_ticks: Decimal = Decimal("1")
    secondary_markout_penalty_edge_ticks: int = 1
    secondary_markout_penalty_size_factor: Decimal = Decimal("0.50")
    entry_markout_window_ms: int = 1000
    entry_markout_trigger_samples: int = 3
    entry_markout_adverse_threshold_ticks: Decimal = Decimal("1")
    entry_markout_penalty_size_factor: Decimal = Decimal("0.50")
    entry_profit_density_enabled: bool = False
    entry_profit_density_window_minutes: int = 60
    entry_profit_density_soft_per10k: Decimal = Decimal("0.15")
    entry_profit_density_hard_per10k: Decimal = Decimal("0.05")
    entry_profit_density_soft_size_factor: Decimal = Decimal("0.70")
    entry_profit_density_hard_size_factor: Decimal = Decimal("0.40")
    rebalance_profit_density_enabled: bool = False
    rebalance_profit_density_window_minutes: int = 60
    rebalance_profit_density_soft_per10k: Decimal = Decimal("0.10")
    rebalance_profit_density_hard_per10k: Decimal = Decimal("0")
    rebalance_profit_density_soft_size_factor: Decimal = Decimal("0.70")
    rebalance_profit_density_hard_size_factor: Decimal = Decimal("0.40")
    rebalance_profit_density_soft_extra_ticks: int = 1
    rebalance_profit_density_hard_extra_ticks: int = 2
    sell_drought_guard_enabled: bool = False
    sell_drought_inventory_ratio_pct: Decimal = Decimal("0.60")
    sell_drought_rebalance_window_seconds: float = 900.0
    toxicity_severe_extra_ticks: Decimal = Decimal("1")
    toxicity_severe_size_factor: Decimal = Decimal("0.25")
    toxicity_severe_extra_edge_ticks: int = 1
    toxicity_disable_second_entry_layer: bool = True
    favorable_size_spread_ticks: int = 0
    favorable_size_multiplier: Decimal = Decimal("1")
    normal_buy_price_cap: Decimal = Decimal("0")
    normal_sell_price_floor: Decimal = Decimal("0")
    preserve_entry_queue: bool = True
    preserve_rebalance_queue: bool = True


@dataclass
class RiskConfig:
    stale_book_ms: int = 15000
    cancel_orders_on_stale_book: bool = False
    max_reconnects_per_5m: int = 3
    daily_loss_limit_quote: Decimal = Decimal("50")
    realized_loss_shutdown_quote: Decimal = Decimal("0")
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
    live_allowed_instruments: list[str] = field(default_factory=lambda: ["USDC-USDT", "USDG-USDT"])
    observe_only_instruments: list[str] = field(default_factory=lambda: ["DAI-USDT", "PYUSD-USDT"])
    zero_fee_instruments: list[str] = field(default_factory=lambda: ["USDC-USDT"])
    simulated_rest_trade_instruments: list[str] = field(default_factory=lambda: ["USDG-USDT"])
    max_managed_orders_per_side: int = 1
    max_consistency_failures: int = 3
    cancel_managed_on_consistency_failure: bool = False
    balance_consistency_tolerance_quote: Decimal = Decimal("1")
    require_passive_prices_on_resync: bool = True
    startup_recovery_enabled: bool = False


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
    stop_request_path: str = "data/stop.request"
    shared_route_ledger_path: str = "data/route_ledger.jsonl"
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


def _load_optional_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _default_secret_config_path(*, config_path: Path, exchange_name: str) -> Path:
    if exchange_name == "binance":
        return config_path.with_name("secret.binance.yaml")
    return config_path.with_name("secret.yaml")


def _resolve_runtime_path(raw_path: str, *, config_path: Path) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)

    project_root = config_path.parent.parent
    workspace_root = project_root.parent
    if path.parts and path.parts[0] == project_root.name:
        preferred = workspace_root / path
        return str(preferred)
    else:
        preferred = project_root / path
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


def _telemetry_environment_label(*, mode: str, simulated: bool) -> str:
    if mode == "shadow":
        return "shadow"
    return "sim" if simulated else "live"


def _apply_environment_suffix(raw_path: str, *, mode: str, simulated: bool) -> str:
    path = Path(raw_path)
    env_suffix = f".{_telemetry_environment_label(mode=mode, simulated=simulated)}"
    stem = path.stem
    if stem.endswith(".shadow") or stem.endswith(".sim") or stem.endswith(".live"):
        return str(path)
    return str(path.with_name(f"{stem}{env_suffix}{path.suffix}"))


def load_config(
    path: str | os.PathLike[str],
    mode_override: str | None = None,
    *,
    validate_live_credentials: bool = True,
) -> BotConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = _load_optional_yaml(config_path)
    exchange_name = str((raw.get("exchange") or {}).get("name") or "okx").lower()
    secret_raw = _load_optional_yaml(_default_secret_config_path(config_path=config_path, exchange_name=exchange_name))
    config = BotConfig()
    config.mode = mode_override or raw.get("mode", config.mode)
    config.managed_prefix = str(raw.get("managed_prefix") or config.managed_prefix)

    _merge_dataclass(config.exchange, raw.get("exchange", {}))
    _merge_dataclass(config.exchange, secret_raw.get("exchange", {}))
    _merge_dataclass(config.trading, raw.get("trading", {}))
    _merge_dataclass(config.strategy, raw.get("strategy", {}))
    _merge_dataclass(config.risk, raw.get("risk", {}))
    _merge_dataclass(config.shadow, raw.get("shadow", {}))
    _merge_dataclass(config.telemetry, raw.get("telemetry", {}))
    config.telemetry.journal_path = _resolve_runtime_path(config.telemetry.journal_path, config_path=config_path)
    config.telemetry.sqlite_path = _resolve_runtime_path(config.telemetry.sqlite_path, config_path=config_path)
    config.telemetry.state_path = _resolve_runtime_path(config.telemetry.state_path, config_path=config_path)
    config.telemetry.stop_request_path = _resolve_runtime_path(config.telemetry.stop_request_path, config_path=config_path)
    config.telemetry.shared_route_ledger_path = _resolve_runtime_path(config.telemetry.shared_route_ledger_path, config_path=config_path)
    config.strategy.release_only_shared_state_paths = [
        _resolve_runtime_path(path, config_path=config_path)
        for path in config.strategy.release_only_shared_state_paths
    ]

    config.exchange.apply_env()
    config.exchange.apply_runtime_defaults()
    config.telemetry.journal_path = _apply_environment_suffix(
        config.telemetry.journal_path,
        mode=config.mode,
        simulated=config.exchange.simulated,
    )
    config.telemetry.sqlite_path = _apply_environment_suffix(
        config.telemetry.sqlite_path,
        mode=config.mode,
        simulated=config.exchange.simulated,
    )
    config.telemetry.state_path = _apply_environment_suffix(
        config.telemetry.state_path,
        mode=config.mode,
        simulated=config.exchange.simulated,
    )
    config.telemetry.stop_request_path = _apply_environment_suffix(
        config.telemetry.stop_request_path,
        mode=config.mode,
        simulated=config.exchange.simulated,
    )
    config.telemetry.shared_route_ledger_path = _apply_environment_suffix(
        config.telemetry.shared_route_ledger_path,
        mode=config.mode,
        simulated=config.exchange.simulated,
    )
    config.strategy.release_only_shared_state_paths = [
        _apply_environment_suffix(path, mode=config.mode, simulated=config.exchange.simulated)
        for path in config.strategy.release_only_shared_state_paths
    ]
    if config.mode == "live" and validate_live_credentials:
        if config.exchange.name == "binance":
            required = {
                "BINANCE_API_KEY": config.exchange.api_key,
                "BINANCE_SECRET_KEY": config.exchange.secret_key,
            }
        else:
            required = {
                "OKX_API_KEY": config.exchange.api_key,
                "OKX_SECRET_KEY": config.exchange.secret_key,
                "OKX_PASSPHRASE": config.exchange.passphrase,
            }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Live mode requires credentials: {', '.join(missing)}")
    return config
