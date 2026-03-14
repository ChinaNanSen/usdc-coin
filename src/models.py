from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence


ZERO = Decimal("0")


@dataclass(frozen=True)
class InstrumentMeta:
    inst_id: str
    inst_type: str
    base_ccy: str
    quote_ccy: str
    tick_size: Decimal
    lot_size: Decimal
    min_size: Decimal
    max_market_amount: Decimal
    max_limit_amount: Decimal
    inst_id_code: str | None = None
    state: str = "live"
    rule_type: str = "normal"


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal
    order_count: int = 0


@dataclass(frozen=True)
class BookSnapshot:
    ts_ms: int
    bids: list[BookLevel]
    asks: list[BookLevel]
    received_ms: int | None = None

    @property
    def last_update_ms(self) -> int:
        return self.received_ms or self.ts_ms

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def spread(self) -> Decimal:
        if not self.best_bid or not self.best_ask:
            return ZERO
        return self.best_ask.price - self.best_bid.price

    @property
    def mid(self) -> Decimal | None:
        if not self.best_bid or not self.best_ask:
            return None
        return (self.best_bid.price + self.best_ask.price) / Decimal("2")


@dataclass(frozen=True)
class TradeTick:
    ts_ms: int
    price: Decimal
    size: Decimal
    side: str
    received_ms: int | None = None
    trade_id: str | None = None
    order_price: Decimal | None = None

    @property
    def last_update_ms(self) -> int:
        return self.received_ms or self.ts_ms


@dataclass
class Balance:
    ccy: str
    total: Decimal
    available: Decimal
    frozen: Decimal = ZERO


@dataclass
class LiveOrder:
    inst_id: str
    side: str
    ord_id: str
    cl_ord_id: str
    price: Decimal
    size: Decimal
    filled_size: Decimal
    state: str
    created_at_ms: int
    updated_at_ms: int
    source: str = "rest"
    queue_ahead_size: Decimal = ZERO
    cancel_requested: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.state.lower() in {"filled", "canceled", "cancelled", "mmp_canceled"}

    @property
    def remaining_size(self) -> Decimal:
        remaining = self.size - self.filled_size
        return remaining if remaining > ZERO else ZERO


@dataclass(frozen=True)
class FeeSnapshot:
    inst_type: str
    inst_id: str
    maker: Decimal
    taker: Decimal
    effective_maker: Decimal
    effective_taker: Decimal
    checked_at_ms: int
    fee_type: str = ""
    source: str = "account_trade_fee"
    zero_fee_override: bool = False


@dataclass(frozen=True)
class OrderIntent:
    side: str
    price: Decimal
    quote_notional: Decimal
    reason: str
    base_size: Decimal | None = None


@dataclass
class StrategyLot:
    qty: Decimal
    price: Decimal
    ts_ms: int
    cl_ord_id: str = ""
    reference_best_bid: Decimal | None = None
    reference_best_ask: Decimal | None = None


@dataclass(frozen=True)
class RiskStatus:
    ok: bool
    reason: str
    allow_bid: bool
    allow_ask: bool
    runtime_state: str = "READY"


@dataclass(frozen=True)
class QuoteDecision:
    reason: str
    bid: OrderIntent | None = None
    ask: OrderIntent | None = None
    bid_layers: tuple[OrderIntent, ...] = ()
    ask_layers: tuple[OrderIntent, ...] = ()
    inventory_ratio: Decimal | None = None
    spread_ticks: Decimal = ZERO

    def __post_init__(self) -> None:
        bid_layers = self._normalize_layers(self.bid_layers, fallback=self.bid)
        ask_layers = self._normalize_layers(self.ask_layers, fallback=self.ask)
        object.__setattr__(self, "bid_layers", bid_layers)
        object.__setattr__(self, "ask_layers", ask_layers)
        object.__setattr__(self, "bid", bid_layers[0] if bid_layers else None)
        object.__setattr__(self, "ask", ask_layers[0] if ask_layers else None)

    @staticmethod
    def _normalize_layers(
        layers: Sequence[OrderIntent] | None,
        *,
        fallback: OrderIntent | None,
    ) -> tuple[OrderIntent, ...]:
        normalized = tuple(layer for layer in (layers or ()) if layer is not None)
        if normalized:
            return normalized
        if fallback is None:
            return ()
        return (fallback,)

    def intents_for_side(self, side: str) -> tuple[OrderIntent, ...]:
        if side == "buy":
            return self.bid_layers
        if side == "sell":
            return self.ask_layers
        return ()


@dataclass(frozen=True)
class ConsistencyReport:
    ok: bool
    reason: str
    cancel_managed: bool = False
    offending_managed_orders: tuple[str, ...] = ()
    foreign_orders: tuple[str, ...] = ()
    managed_buy_orders: int = 0
    managed_sell_orders: int = 0
    pending_buy_notional: Decimal = ZERO
    pending_sell_size: Decimal = ZERO


@dataclass
class EventRecord:
    event: str
    payload: dict[str, Any] = field(default_factory=dict)
