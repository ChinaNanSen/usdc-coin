from __future__ import annotations

from typing import Any


REASON_LABELS = {
    "shutdown": "程序关闭",
    "startup_cleanup": "启动清理旧挂单",
    "public_reconnect": "公共行情重连清理",
    "duplicate_side_order": "同侧重复挂单清理",
    "side_disabled": "该侧当前不该挂单",
    "reprice_or_ttl": "改价或超时重挂",
    "size_below_min": "下单量低于最小限制",
    "join_best_bid": "挂买一排队",
    "join_best_ask": "挂卖一排队",
    "rebalance_open_long": "按已成交仓位回补卖出",
    "rebalance_open_short": "按已成交仓位回补买入",
    "strict_cycle_buy_only": "严格交替：本轮只挂买单",
    "strict_cycle_sell_only": "严格交替：本轮只挂卖单",
}

PLACE_ERROR_LABELS = {
    "51008": "余额不足或可借额度不足",
    "51000": "参数错误",
}

CANCEL_ERROR_LABELS = {
    "51400": "撤单时订单已终态",
}


def translate_reason(reason: str | None) -> str:
    if not reason:
        return "-"
    return REASON_LABELS.get(str(reason), str(reason))


def summarize_okx_error(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "-"
    data = payload.get("data") or []
    if not data:
        code = str(payload.get("code") or "")
        msg = str(payload.get("msg") or "")
        if code and msg:
            return f"{code} {msg}"
        return msg or code or "-"

    parts: list[str] = []
    for item in data[:3]:
        s_code = str(item.get("sCode") or "")
        s_msg = str(item.get("sMsg") or "")
        label = PLACE_ERROR_LABELS.get(s_code) or CANCEL_ERROR_LABELS.get(s_code) or s_msg or s_code
        if s_code:
            parts.append(f"{s_code} {label}".strip())
        elif label:
            parts.append(label)
    return "；".join(parts) if parts else "-"
