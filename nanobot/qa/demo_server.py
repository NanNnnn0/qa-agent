"""Minimal demo shop API used by the QA Agent quickstart.

``python -m nanobot.cli qa demo-server`` serves:

- ``GET  /api/products``  -> ``{"code":0,"items":[...]}``
- ``POST /api/orders``    -> 201 ``{"code":0,"data":{"orderId":...}}``
- ``GET  /api/orders/{id}``
- ``GET  /health``

Intentional defects exist so the demo has something to find:
an invalid ``qty`` is rejected, an over-stock order returns 400/1001, and an
unknown SKU returns 404/1002.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

_PRODUCTS = {
    "A-1": {"sku": "A-1", "name": "无线耳机", "price": 199, "stock": 5},
    "B-2": {"sku": "B-2", "name": "机械键盘", "price": 399, "stock": 0},
}
_ORDERS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_COUNTER = {"n": 0}


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "QADemo/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # keep the demo console quiet

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/health":
            _json_response(self, 200, {"ok": True})
            return
        if path == "/api/products":
            _json_response(self, 200, {"code": 0, "items": list(_PRODUCTS.values())})
            return
        if path.startswith("/api/orders/"):
            order_id = path.rsplit("/", 1)[-1]
            order = _ORDERS.get(order_id)
            if order is None:
                _json_response(self, 404, {"code": 1002, "message": "order not found"})
                return
            _json_response(self, 200, {"code": 0, "data": order})
            return
        _json_response(self, 404, {"code": 1004, "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path != "/api/orders":
            _json_response(self, 404, {"code": 1004, "message": "not found"})
            return
        payload = self._body()
        sku = payload.get("sku")
        qty = payload.get("qty")
        if not isinstance(sku, str) or not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            _json_response(self, 400, {"code": 1000, "message": "invalid parameter"})
            return
        product = _PRODUCTS.get(sku)
        if product is None:
            _json_response(self, 404, {"code": 1002, "message": "sku not found"})
            return
        if qty > int(product["stock"]):
            _json_response(self, 400, {"code": 1001, "message": "insufficient stock"})
            return
        with _LOCK:
            _COUNTER["n"] += 1
            order_id = f"ord_{_COUNTER['n']:04d}"
            order = {
                "orderId": order_id,
                "sku": sku,
                "qty": qty,
                "amount": qty * int(product["price"]),
                "status": "CREATED",
            }
            _ORDERS[order_id] = order
            product["stock"] = int(product["stock"]) - qty
        _json_response(self, 201, {"code": 0, "data": order})


def serve(host: str = "127.0.0.1", port: int = 8799) -> None:
    """Run the demo API until interrupted."""
    httpd = ThreadingHTTPServer((host, port), DemoHandler)
    print(f"QA demo API listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":  # pragma: no cover
    serve()
