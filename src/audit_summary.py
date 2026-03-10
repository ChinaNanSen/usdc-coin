from __future__ import annotations

import json
import sqlite3
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import BotConfig
from .utils import decimal_to_str


def render_audit_summary(config: BotConfig, *, run_id: str | None = None) -> str:
    lines: list[str] = []

    snapshot_lines = _render_snapshot_section(config)
    if snapshot_lines:
        lines.extend(snapshot_lines)

    latest_run = run_id or _latest_run_id(config.telemetry.sqlite_path)
    if latest_run:
        if lines:
            lines.append("")
        lines.extend(_render_run_section(config.telemetry.sqlite_path, latest_run, title="最新运行"))

    filled_run = _latest_run_with_fills(config.telemetry.sqlite_path, exclude_run_id=latest_run)
    if filled_run:
        if lines:
            lines.append("")
        lines.extend(_render_run_section(config.telemetry.sqlite_path, filled_run, title="最近一次有成交的运行"))

    if not lines:
        return "未找到快照或审计数据。"
    return "\n".join(lines)


def _render_snapshot_section(config: BotConfig) -> list[str]:
    snapshot_path = Path(config.telemetry.state_path)
    if not snapshot_path.exists():
        return []

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    instrument = payload.get("instrument") or {}
    balances = payload.get("balances") or {}
    book = payload.get("book") or {}
    runtime_state = payload.get("runtime_state") or "-"
    runtime_reason = payload.get("runtime_reason") or "-"
    initial_nav = _optional_decimal(payload.get("initial_nav_quote"))
    base_ccy = instrument.get("base_ccy") or config.trading.base_ccy
    quote_ccy = instrument.get("quote_ccy") or config.trading.quote_ccy

    best_bid = _extract_price(book.get("bids"), 0)
    best_ask = _extract_price(book.get("asks"), 0)
    mid = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / Decimal("2")
    elif best_bid is not None:
        mid = best_bid
    elif best_ask is not None:
        mid = best_ask

    base_total = _balance_total(balances, base_ccy)
    quote_total = _balance_total(balances, quote_ccy)
    nav = base_total * mid + quote_total if mid is not None else None
    pnl = nav - initial_nav if nav is not None and initial_nav is not None else None
    inventory_ratio = (base_total * mid / nav) if nav is not None and mid is not None and nav > 0 else None
    live_realized = _optional_decimal(payload.get("live_realized_pnl_quote"))
    live_unrealized = _optional_decimal(payload.get("live_unrealized_pnl_quote"))
    strategy_position_base = _optional_decimal(payload.get("strategy_position_base"))

    mode_text = "OKX模拟盘" if config.mode == "live" and config.exchange.simulated else ("实盘" if config.mode == "live" else "影子模拟")
    lines = [
        "当前快照",
        f"- 模式={mode_text}",
        f"- 状态={_translate_reason(runtime_state)} | 原因={_translate_reason(runtime_reason)}",
        f"- 当前盘口: 买一={_fmt(best_bid)} 卖一={_fmt(best_ask)} 中间价={_fmt(mid)}",
        f"- {base_ccy}: 总额={_fmt(base_total)}",
        f"- {quote_ccy}: 总额={_fmt(quote_total)}",
        f"- 策略净值(U)={_fmt(nav)} | 本轮盈亏(U)={_fmt_signed(pnl)} | 库存占比={_fmt_pct(inventory_ratio)}",
        f"- 已观测成交次数={payload.get('observed_fill_count', 0)} | 已观测成交额(U)={_fmt(_optional_decimal(payload.get('observed_fill_volume_quote')))}",
    ]
    if live_realized is not None or live_unrealized is not None or strategy_position_base is not None:
        lines.append(
            f"- 已实现(U)={_fmt_signed(live_realized)} | 库存浮盈(U)={_fmt_signed(live_unrealized)} | 待回补仓位({base_ccy})={_fmt_signed(strategy_position_base)}"
        )
    return lines


def _render_run_section(sqlite_path: str, run_id: str, *, title: str) -> list[str]:
    events = _load_run_events(sqlite_path, run_id)
    if not events:
        return [title, f"- run_id={run_id}", "- 未找到事件"]

    counts = Counter(event for _, event, _ in events)
    cancel_reasons: Counter[str] = Counter()
    decision_reasons: Counter[str] = Counter()
    fills_by_order: dict[str, dict[str, Any]] = {}

    for _, event, payload in events:
        if event == "cancel_order":
            cancel_reasons[str(payload.get("reason_zh") or _translate_reason(str(payload.get("reason") or "-")))] += 1
            continue
        if event == "decision":
            reason = ((payload.get("decision") or {}).get("reason")) or "-"
            decision_reasons[str(reason)] += 1
            continue
        if event != "order_update":
            continue

        order = payload.get("order") or {}
        filled_size = _optional_decimal(order.get("filled_size"))
        if filled_size is None or filled_size <= 0:
            continue

        cl_ord_id = str(order.get("cl_ord_id") or order.get("ord_id") or f"unknown-{len(fills_by_order)}")
        previous = fills_by_order.get(cl_ord_id)
        if previous is not None and filled_size <= previous["filled_size"]:
            continue

        fills_by_order[cl_ord_id] = {
            "side": str(order.get("side") or "-"),
            "price": _optional_decimal(order.get("price")) or Decimal("0"),
            "filled_size": filled_size,
            "state": str(order.get("state") or "-"),
        }

    buy_count = 0
    sell_count = 0
    buy_notional = Decimal("0")
    sell_notional = Decimal("0")
    buy_size = Decimal("0")
    sell_size = Decimal("0")
    for fill in fills_by_order.values():
        notional = fill["filled_size"] * fill["price"]
        if fill["side"] == "buy":
            buy_count += 1
            buy_notional += notional
            buy_size += fill["filled_size"]
        elif fill["side"] == "sell":
            sell_count += 1
            sell_notional += notional
            sell_size += fill["filled_size"]

    start_ms = events[0][0]
    end_ms = events[-1][0]
    duration_seconds = Decimal(end_ms - start_ms) / Decimal("1000")

    roundtrip_pnl: Decimal | None = None
    if buy_size > 0 and sell_size > 0 and buy_size == sell_size:
        roundtrip_pnl = sell_notional - buy_notional

    lines = [
        title,
        f"- run_id={run_id}",
        f"- 时长={_fmt_seconds(duration_seconds)} | 事件数={len(events)}",
        (
            f"- 下单={counts.get('place_order', 0)} "
            f"撤单={counts.get('cancel_order', 0)} "
            f"订单回报={counts.get('order_update', 0)} "
            f"成交订单={buy_count + sell_count}"
        ),
        (
            f"- 买入成交={buy_count}笔/{_fmt(buy_notional)}U "
            f"卖出成交={sell_count}笔/{_fmt(sell_notional)}U "
            f"往返价差毛收益估算(U)={_fmt_signed(roundtrip_pnl)}"
        ),
    ]
    if roundtrip_pnl is None and (buy_count or sell_count):
        lines.append("- 说明: 当前只有单边成交，或买卖数量未配平，暂不把成交额差额当成利润")
    if cancel_reasons:
        translated = "，".join(f"{reason} {count}" for reason, count in cancel_reasons.most_common())
        lines.append(f"- 撤单主因: {translated}")
    if decision_reasons:
        translated = "，".join(f"{_translate_reason(reason)} {count}" for reason, count in decision_reasons.most_common(3))
        lines.append(f"- 决策主因: {translated}")
    return lines


def _load_run_events(sqlite_path: str, run_id: str) -> list[tuple[int, str, dict[str, Any]]]:
    path = Path(sqlite_path)
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT ts_ms, event, payload_json FROM audit_events WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [(int(ts_ms), str(event), json.loads(payload_json)) for ts_ms, event, payload_json in rows]


def _latest_run_id(sqlite_path: str) -> str | None:
    path = Path(sqlite_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(
            "SELECT run_id FROM audit_events WHERE run_id IS NOT NULL GROUP BY run_id ORDER BY MAX(ts_ms) DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else None


def _latest_run_with_fills(sqlite_path: str, *, exclude_run_id: str | None = None) -> str | None:
    path = Path(sqlite_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path))
    try:
        run_rows = conn.execute(
            "SELECT run_id FROM audit_events WHERE run_id IS NOT NULL GROUP BY run_id ORDER BY MAX(ts_ms) DESC"
        ).fetchall()
        for (run_id,) in run_rows:
            if not run_id or run_id == exclude_run_id:
                continue
            has_fill = conn.execute(
                """
                SELECT 1
                FROM audit_events
                WHERE run_id = ?
                  AND event = 'order_update'
                  AND CAST(json_extract(payload_json, '$.order.filled_size') AS REAL) > 0
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if has_fill:
                return str(run_id)
    finally:
        conn.close()
    return None


def _extract_price(levels: Any, index: int) -> Decimal | None:
    if not isinstance(levels, list) or len(levels) <= index:
        return None
    level = levels[index] or {}
    return _optional_decimal(level.get("price"))


def _balance_total(balances: dict[str, Any], ccy: str) -> Decimal:
    payload = balances.get(ccy) or {}
    return _optional_decimal(payload.get("total")) or Decimal("0")


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return decimal_to_str(value)


def _fmt_signed(value: Decimal | None) -> str:
    if value is None:
        return "-"
    prefix = "+" if value > 0 else ""
    return prefix + decimal_to_str(value)


def _fmt_pct(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return decimal_to_str(value * Decimal("100")) + "%"


def _fmt_seconds(value: Decimal) -> str:
    if value < 60:
        return decimal_to_str(value) + "秒"
    minutes = int(value // Decimal("60"))
    seconds = value - Decimal(minutes) * Decimal("60")
    return f"{minutes}分{decimal_to_str(seconds)}秒"


def _translate_reason(value: str) -> str:
    mapping = {
        "INIT": "初始化",
        "READY": "就绪",
        "QUOTING": "报价中",
        "PAUSED": "暂停",
        "STOPPED": "停止",
        "REDUCE_ONLY": "仅减仓",
        "ok": "正常",
        "two_sided": "双边报价",
        "inventory_low_bid_only": "库存偏低，只挂买单",
        "inventory_high_ask_only": "库存偏高，只挂卖单",
        "fill_rebalance_buy_only": "成交后回补，只挂买单",
        "fill_rebalance_sell_only": "成交后回补，只挂卖单",
        "strict_cycle_buy_only": "严格交替：本轮只挂买单",
        "strict_cycle_sell_only": "严格交替：本轮只挂卖单",
        "streams not ready": "流未就绪",
        "too many place failures": "下单失败次数过多",
        "too many reconnects in 5m": "5分钟内重连次数过多",
        "reduce_only_inventory_high": "库存过高，仅减仓",
        "reduce_only_inventory_low": "库存过低，仅减仓",
        "inventory/balance blocks both sides": "余额或库存限制，双边都不能挂",
        "missing market bootstrap": "缺少启动行情",
        "shutdown": "程序关闭",
        "booting": "启动中",
        "reprice_or_ttl": "超时或需要重挂",
        "side_disabled": "该侧当前禁挂",
        "-": "-",
    }
    if value in mapping:
        return mapping[value]
    prefix_mapping = {
        "stale book:": "盘口过旧:",
        "pause active:": "暂停中:",
        "place failure cooldown:": "下单失败冷却中:",
        "cancel failure cooldown:": "撤单失败冷却中:",
        "spread too tight:": "价差过小:",
        "visible depth too thin:": "可见深度不足:",
        "peg deviation too high:": "脱锚偏离过大:",
        "daily loss limit hit:": "触发日内亏损限制:",
        "resync required:": "需要重同步:",
    }
    for prefix, translated in prefix_mapping.items():
        if str(value).startswith(prefix):
            return translated + str(value)[len(prefix):]
    return value
