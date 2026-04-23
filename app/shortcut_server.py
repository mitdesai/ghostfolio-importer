"""HTTP server for the iOS Shortcut to POST trades and portfolio snapshot.

Endpoints:
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

  GET /snapshot
  Response: HTML portfolio snapshot (no auth — read-only)

  GET /snapshot/pdf
  Response: PDF download of portfolio snapshot (no auth — read-only)
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date as date_cls, datetime
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .activity import Activity
from .dedup import DedupStore
from .snapshot import fetch_snapshot
from .snapshot_template import render_html

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

            def _check_auth(self) -> bool:
                if self.headers.get("X-Auth-Token") != server_ref.auth_token:
                    self._send_json(401, {"error": "unauthorized"})
                    return False
                return True

            def _send_html(self, status, html):
                body = html.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_pdf(self, pdf_bytes, filename):
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(pdf_bytes)))
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{filename}"',
                )
                self.end_headers()
                self.wfile.write(pdf_bytes)

            def do_GET(self):
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query)
                path = parsed.path
                public = {
                    "/health": lambda: self._send_json(200, {"ok": True}),
                    "/snapshot": lambda: self._send_html(
                        200, server_ref._render_snapshot(show_details=True),
                    ),
                    "/snapshot/pdf": lambda: server_ref._send_snapshot_pdf(
                        self, show_details="1" in qs.get("details", []),
                    ),
                }
                handler = public.get(path)
                if handler:
                    try:
                        handler()
                    except Exception as e:
                        log.error("%s failed: %s", self.path, e, exc_info=True)
                        self._send_json(500, {"error": str(e)})
                    return
                self._send_json(404, {"error": "not found"})

            def _read_json_body(self) -> dict | None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length else b""
                try:
                    return json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "invalid json"})
                    return None

            def _handle_trade(self):
                data = self._read_json_body()
                if data is None:
                    return
                try:
                    activity = server_ref._build_activity(data)
                except ValueError as e:
                    self._send_json(400, {"error": str(e)})
                    return
                imported, fp = server_ref._import(activity)
                self._send_json(200, {"imported": imported, "fingerprint": fp})

            def do_POST(self):
                if self.path != "/trade":
                    self._send_json(404, {"error": "not found"})
                    return
                if not self._check_auth():
                    return
                self._handle_trade()

        return Handler

    def _render_snapshot(self, show_details: bool = True) -> str:
        snap = fetch_snapshot(self.client, currency=self.currency)
        return render_html(snap, show_account_details=show_details)

    def _send_snapshot_pdf(self, handler, show_details: bool = False) -> None:
        snap = fetch_snapshot(self.client, currency=self.currency)
        from weasyprint import HTML as WeasyHTML
        html = render_html(snap, show_account_details=show_details)
        pdf_bytes = WeasyHTML(string=html).write_pdf()
        suffix = "-detailed" if show_details else ""
        filename = f"portfolio-snapshot{suffix}-{snap.report_date.isoformat()}.pdf"
        handler._send_pdf(pdf_bytes, filename)

    @staticmethod
    def _require(data: dict, key: str) -> str:
        v = data.get(key)
        if v is None or v == "":
            raise ValueError(f"missing field: {key}")
        return str(v).strip()

    @staticmethod
    def _parse_trade_date(raw: str | None) -> date_cls:
        if not raw:
            return date_cls.today()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("date must be YYYY-MM-DD")

    def _build_activity(self, data: dict) -> Activity:
        account_key = self._require(data, "account")
        if account_key not in self.account_map:
            raise ValueError(
                f"unknown account '{account_key}'. "
                f"Expected one of: {sorted(self.account_map)}"
            )

        action = self._require(data, "action").upper()
        if action not in ("BUY", "SELL"):
            raise ValueError("action must be BUY or SELL")

        try:
            quantity = Decimal(self._require(data, "quantity"))
            unit_price = Decimal(self._require(data, "unit_price"))
            fee = Decimal(str(data.get("fee", "0")))
        except InvalidOperation as e:
            raise ValueError(f"invalid number: {e}")

        if quantity <= 0 or unit_price <= 0:
            raise ValueError("quantity and unit_price must be > 0")

        return Activity(
            account_id=self.account_map[account_key],
            symbol=self._require(data, "symbol").upper(),
            data_source="YAHOO",
            currency=self.currency,
            date=self._parse_trade_date(data.get("date")),
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
