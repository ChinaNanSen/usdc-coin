from __future__ import annotations

from .utils import hmac_sha256_base64


class OKXSigner:
    def __init__(self, api_key: str, secret_key: str, passphrase: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase

    def sign(self, timestamp: str, method: str, path_with_query: str, body: str = "") -> str:
        message = f"{timestamp}{method.upper()}{path_with_query}{body}"
        return hmac_sha256_base64(self.secret_key, message)

    def rest_headers(self, timestamp: str, method: str, path_with_query: str, body: str = "") -> dict[str, str]:
        return {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": self.sign(timestamp, method, path_with_query, body),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    def ws_login_args(self, timestamp: str) -> dict[str, str]:
        return {
            "apiKey": self.api_key,
            "passphrase": self.passphrase,
            "timestamp": timestamp,
            "sign": self.sign(timestamp, "GET", "/users/self/verify"),
        }
