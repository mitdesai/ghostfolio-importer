"""Thin wrapper around Ghostfolio's HTTP API for creating orders."""
from __future__ import annotations

import logging
from datetime import date as date_cls, datetime, time, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .activity import Activity

log = logging.getLogger(__name__)


def serialize_date_as_local_noon(d: date_cls, tz: ZoneInfo) -> str:
    """Anchor the date at noon in the given tz, then serialize as UTC.

    Why: if we sent "YYYY-MM-DD", Ghostfolio stores as UTC midnight.
    In a Pacific-time browser, UTC midnight displays as 5pm the *previous*
    day — a trade from April 15 shows as April 14. Anchoring at noon
    local time keeps the date stable against any reasonable display TZ.
    """
    local_noon = datetime.combine(d, time(12, 0), tzinfo=tz)
    utc = local_noon.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def resolve_tz(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        log.warning("invalid TZ %r, falling back to UTC", tz_name)
        return ZoneInfo("UTC")


class GhostfolioClient:
    """Handles the quirks of Ghostfolio's auth (Bearer JWT via /auth)
    and provides a clean create_order() method.
    """

    def __init__(
        self,
        base_url: str,
        access_token: str,
        tz: str = "UTC",
        manual_symbols: frozenset = frozenset(),
        timeout: float = 15.0,
    ):
        self._base = base_url.rstrip("/")
        self._access_token = access_token
        self._bearer: str | None = None
        self._client = httpx.Client(timeout=timeout)
        self._tz = resolve_tz(tz)
        self._manual_symbols = manual_symbols

    # --- auth ---

    def _authenticate(self) -> None:
        """Exchange the Ghostfolio "security token" for a short-lived JWT."""
        r = self._client.post(
            f"{self._base}/api/v1/auth/anonymous",
            json={"accessToken": self._access_token},
        )
        r.raise_for_status()
        self._bearer = r.json()["authToken"]

    def _headers(self) -> dict[str, str]:
        if not self._bearer:
            self._authenticate()
        return {"Authorization": f"Bearer {self._bearer}"}

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Wrap requests with one-shot re-auth on 401."""
        r = self._client.request(
            method, f"{self._base}{path}", headers=self._headers(), **kwargs
        )
        if r.status_code == 401:
            self._bearer = None
            r = self._client.request(
                method, f"{self._base}{path}", headers=self._headers(), **kwargs
            )
        return r

    # --- public API ---

    def health(self) -> bool:
        try:
            r = self._client.get(f"{self._base}/api/v1/health", timeout=5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def list_accounts(self) -> list[dict[str, Any]]:
        """Useful one-off tool for discovering your ACCOUNT_MAP values."""
        r = self._request("GET", "/api/v1/account")
        r.raise_for_status()
        return r.json().get("accounts", [])

    def _serialize_date(self, d) -> str:
        return serialize_date_as_local_noon(d, self._tz)

    def create_order(self, activity: Activity) -> dict[str, Any]:
        """POST /api/v1/order. Returns the created order JSON."""
        data_source = (
            "MANUAL"
            if activity.symbol in self._manual_symbols
            else activity.data_source
        )
        if data_source == "MANUAL":
            log.debug("using MANUAL data source for delisted symbol %s",
                      activity.symbol)
        body = {
            "accountId": activity.account_id,
            "currency": activity.currency,
            "dataSource": data_source,
            "date": self._serialize_date(activity.date),
            "fee": float(activity.fee),
            "quantity": float(activity.quantity),
            "symbol": activity.symbol,
            "type": activity.action.upper(),
            "unitPrice": float(activity.unit_price),
        }
        r = self._request("POST", "/api/v1/order", json=body)
        if r.status_code >= 400:
            log.error(
                "create_order failed (status=%s): %s | body=%s",
                r.status_code, r.text, body,
            )
            r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()
