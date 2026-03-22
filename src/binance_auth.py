from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlencode


class BinanceSigner:
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key

    def sign_query(self, params: dict[str, str]) -> str:
        ordered = [(key, params[key]) for key in sorted(params.keys())]
        query = urlencode(ordered)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={signature}" if query else f"signature={signature}"

    def api_key_headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key}
