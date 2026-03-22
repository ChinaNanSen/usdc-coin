from __future__ import annotations

from typing import Any


class ExchangeAPIError(RuntimeError):
    def __init__(
        self,
        *,
        path: str,
        code: str = "",
        msg: str = "",
        status_code: int | None = None,
        data: list[dict[str, Any]] | None = None,
    ):
        self.path = path
        self.code = str(code or "")
        self.msg = str(msg or "")
        self.status_code = status_code
        self.data = data or []
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        parts = [self.path]
        if self.status_code is not None:
            parts.append(f"http_status={self.status_code}")
        if self.code:
            parts.append(f"code={self.code}")
        if self.msg:
            parts.append(f"msg={self.msg}")
        item_details = self._format_item_details()
        if item_details:
            parts.append(f"details=[{item_details}]")
        return ": ".join(parts[:1]) + (" " + " ".join(parts[1:]) if len(parts) > 1 else "")

    def _format_item_details(self) -> str:
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "http_status": self.status_code,
            "code": self.code,
            "msg": self.msg,
            "data": self.data,
        }
