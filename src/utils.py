from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any


def parse_decimal(value: Any, default: str = "0") -> Decimal:
    if value in (None, "", "null"):
        return Decimal(default)
    return Decimal(str(value))


def quantize_down(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def quantize_up(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_UP) * step


def decimal_to_str(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def now_ms() -> int:
    return int(time.time() * 1000)


def rest_timestamp(offset_ms: int = 0) -> str:
    ts = (time.time() * 1000 + offset_ms) / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ws_login_timestamp(offset_ms: int = 0) -> str:
    return str(int((time.time() * 1000 + offset_ms) // 1000))


def hmac_sha256_base64(secret_key: str, payload: str) -> str:
    mac = hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), digestmod=hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def managed_id_token(prefix: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9]", "", prefix or "").lower()
    base = sanitized[:10] or "bot"
    return f"{base}m"


def build_cl_ord_id(prefix: str, side: str) -> str:
    token = managed_id_token(prefix)
    side_sanitized = re.sub(r"[^A-Za-z0-9]", "", side or "").lower()
    side_code = (side_sanitized[:1] or "x")
    max_random_len = max(8, 32 - len(token) - len(side_code))
    random_part = uuid.uuid4().hex[: min(20, max_random_len)]
    return f"{token}{side_code}{random_part}"


def build_req_id(prefix: str, action: str) -> str:
    token = managed_id_token(prefix)
    action_sanitized = re.sub(r"[^A-Za-z0-9]", "", action or "").lower()
    action_code = (action_sanitized[:4] or "req")
    max_random_len = max(8, 32 - len(token) - len(action_code))
    random_part = uuid.uuid4().hex[: min(20, max_random_len)]
    return f"{token}{action_code}{random_part}"


def passive_edge_ticks(
    *,
    side: str,
    price: Decimal,
    best_bid: Decimal | None,
    best_ask: Decimal | None,
    tick_size: Decimal,
) -> int | None:
    if tick_size <= 0 or price <= 0:
        return None
    if side == "buy":
        if best_ask is None:
            return None
        return max(int((best_ask - price) / tick_size), 0)
    if side == "sell":
        if best_bid is None:
            return None
        return max(int((price - best_bid) / tick_size), 0)
    return None


def is_managed_cl_ord_id(cl_ord_id: str, prefix: str) -> bool:
    token = managed_id_token(prefix)
    return str(cl_ord_id or "").startswith(token)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_to_str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return to_jsonable(vars(value))
    return value


def dumps_json(data: Any) -> str:
    return json.dumps(to_jsonable(data), ensure_ascii=False, separators=(",", ":"))
