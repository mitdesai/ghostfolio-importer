"""HTTP server for the iOS Shortcut to POST trades to.

Endpoint:
  POST /trade
  Headers: X-Auth-Token: <HTTP_TOKEN>
  Body (JSON):
    {
      "account": "<account key from ACCOUNT_MAP>",
      "symbol": "TSLA",
      "action": "BUY" | "SELL",
      "quantity": 3,
      "unit_price": 245.10,
      "date": "2025-04-17",    // optional, defaults to today
      "fee": 0                 // optional
    }
  Response: 200 {"imported": bool, "fingerprint": str}
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date as date_cls, datetime
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .activity import Activity
from .dedup import DedupStore

log = logging.getLogger(__name__)


class ShortcutServer:
    def __init__(
        self,
        port: int,
        auth_token: str,
        account_map: dict[str, str],  # key -> UUID
        currency: str,
        client,
        store: DedupStore,
    ):
        if not auth_token:
            raise ValueError("HTTP_TOKEN must be set")
        self.port = port
        self.auth_token = auth_token
        self.account_map = account_map
        self.currency = currency
        self.client = client
        self.store = store

    def _make_handler(self):
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                log.info("http %s - %s", self.address_string(), format % args)

            def _send_json(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/health":
                    self._send_json(200, {"ok": True})
                else:
                    self._send_json(404, {"error": "not found"})

            def do_POST(self):
                if self.path != "/trade":
                    self._send_json(404, {"error": "not found"})
                    return
                if self.headers.get("X-Auth-Token") != server_ref.auth_token:
                    self._send_json(401, {"error": "unauthorized"})
                    return
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length else b""
                try:
                    data = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "invalid json"})
                    return
                try:
                    activity = server_ref._build_activity(data)
                except ValueError as e:
                    self._send_json(400, {"error": str(e)})
                    return
                imported, fp = server_ref._import(activity)
                self._send_json(200, {"imported": imported, "fingerprint": fp})

        return Handler

    def _build_activity(self, data: dict) -> Activity:
        def need(k):
            v = data.get(k)
            if v is None or v == "":
                raise ValueError(f"missing field: {k}")
            return v

        account_key = str(need("account")).strip()
        if account_key not in self.account_map:
            raise ValueError(
                f"unknown account '{account_key}'. "
                f"Expected one of: {sorted(self.account_map)}"
            )

        action = str(need("action")).upper().strip()
        if action not in ("BUY", "SELL"):
            raise ValueError("action must be BUY or SELL")

        try:
            quantity = Decimal(str(need("quantity")))
            unit_price = Decimal(str(need("unit_price")))
            fee = Decimal(str(data.get("fee", "0")))
        except InvalidOperation as e:
            raise ValueError(f"invalid number: {e}")

        if quantity <= 0 or unit_price <= 0:
            raise ValueError("quantity and unit_price must be > 0")

        raw_date = data.get("date")
        if raw_date:
            try:
                trade_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("date must be YYYY-MM-DD")
        else:
            trade_date = date_cls.today()

        return Activity(
            account_id=self.account_map[account_key],
            symbol=str(need("symbol")).upper().strip(),
            data_source="YAHOO",
            currency=self.currency,
            date=trade_date,
            action=action,
            quantity=quantity,
            unit_price=unit_price,
            fee=fee,
            source="shortcut",
        )

    def _import(self, a: Activity) -> tuple[bool, str]:
        fp = a.fingerprint()
        if self.store.has(fp):
            return (False, fp)
        result = self.client.create_order(a)
        self.store.record(
            fp, a.source, a.symbol, a.account_id,
            ghostfolio_id=result.get("id"),
        )
        log.info("imported SHORTCUT %s %s %s qty=%s @ %s",
                 a.action, a.symbol, a.date, a.quantity, a.unit_price)
        return (True, fp)

    def run_forever(self) -> None:
        server = ThreadingHTTPServer(("0.0.0.0", self.port), self._make_handler())
        log.info("Shortcut HTTP endpoint listening on :%d", self.port)
        server.serve_forever()

    def run_in_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, daemon=True, name="http")
        t.start()
        return t
