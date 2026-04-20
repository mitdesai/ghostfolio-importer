"""Tests for the full pipeline: config, parsers, watcher routing, shortcut."""
import json
import os
import sys
import time
import types
import unittest
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

# Stub httpx so ghostfolio.py imports work in the test sandbox
if "httpx" not in sys.modules:
    stub = types.ModuleType("httpx")
    stub.Client = object
    stub.HTTPError = Exception
    sys.modules["httpx"] = stub

from app.activity import Activity
from app.config import _parse_account_map, accounts_by_broker
from app.dedup import DedupStore
from app.fidelity import parse_fidelity_csv
from app.ghostfolio import resolve_tz, serialize_date_as_local_noon
from app.robinhood import parse_robinhood_csv
from app.shortcut_server import ShortcutServer
from app.watcher import CsvDropWatcher
from tests.fixtures import FIDELITY_CSV, ROBINHOOD_CSV


# --- Helpers ---

def _write(tmp, content, name="f.csv"):
    p = Path(tmp) / name
    p.write_text(content)
    return p


def _backdate(path: Path):
    """Backdate mtime past the 3-second watcher guard."""
    old = time.time() - 10
    os.utime(path, (old, old))


def _find_free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --- Config ---

class ConfigTests(unittest.TestCase):
    def test_parse_account_map_basic(self):
        m = _parse_account_map(
            "brokerage-fidelity=uuid1:fidelity,"
            "brokerage-rh=uuid2:robinhood,"
            "hsa=uuid3:manual"
        )
        self.assertEqual(m["brokerage-fidelity"].uuid, "uuid1")
        self.assertEqual(m["brokerage-fidelity"].broker, "fidelity")
        self.assertEqual(m["brokerage-rh"].broker, "robinhood")
        self.assertEqual(m["hsa"].broker, "manual")

    def test_missing_broker_defaults_to_manual(self):
        m = _parse_account_map("hsa=uuid3")
        self.assertEqual(m["hsa"].broker, "manual")

    def test_unknown_broker_falls_back(self):
        m = _parse_account_map("foo=uuid:coinbase")
        self.assertEqual(m["foo"].broker, "manual")

    def test_filter_by_broker(self):
        m = _parse_account_map(
            "a=uuid1:fidelity,b=uuid2:robinhood,c=uuid3:fidelity"
        )
        fid = accounts_by_broker(m, "fidelity")
        self.assertEqual(set(fid), {"a", "c"})


# --- Fidelity parser ---

class FidelityParserTests(unittest.TestCase):
    def test_parses_buy_and_sell_only(self):
        with TemporaryDirectory() as tmp:
            p = _write(tmp, FIDELITY_CSV)
            activities = list(parse_fidelity_csv(p, "acct-uuid"))

            # From the fixture: PATH Buy + TSLA Sell = 2
            # Everything else (REINVESTMENT, DIVIDEND, TRANSFERRED,
            # FDRXX cash, disclaimer) should be skipped
            self.assertEqual(len(activities), 2)

            by_symbol = {a.symbol: a for a in activities}
            path_buy = by_symbol["PATH"]
            self.assertEqual(path_buy.action, "BUY")
            self.assertEqual(path_buy.quantity, Decimal("50"))
            self.assertEqual(path_buy.unit_price, Decimal("16.54"))

            tsla_sell = by_symbol["TSLA"]
            self.assertEqual(tsla_sell.action, "SELL")
            self.assertEqual(tsla_sell.quantity, Decimal("2"))

    def test_skips_missing_header(self):
        with TemporaryDirectory() as tmp:
            p = _write(tmp, "garbage\ndata\n")
            self.assertEqual(list(parse_fidelity_csv(p, "a")), [])

    def test_skips_short_rows(self):
        csv_with_footer = (
            "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
            "Commission ($),Fees ($),Accrued Interest ($),Amount ($),"
            "Cash Balance ($),Settlement Date\n"
            "04/15/2026,YOU BOUGHT TEST (FOO),FOO,TEST,Cash,10,5,,,,-50,100,04/16/2026\n"
            '"Single-column footer row that would crash without the guard"\n'
        )
        with TemporaryDirectory() as tmp:
            p = _write(tmp, csv_with_footer)
            a = list(parse_fidelity_csv(p, "acct"))
            self.assertEqual(len(a), 1)
            self.assertEqual(a[0].symbol, "FOO")


# --- Robinhood parser ---

class RobinhoodParserTests(unittest.TestCase):
    def test_parses_buy_and_sell_only(self):
        with TemporaryDirectory() as tmp:
            p = _write(tmp, ROBINHOOD_CSV)
            activities = list(parse_robinhood_csv(p, "acct-uuid"))

            # From the fixture: ZETA Buy + HNST Sell = 2
            # Skipped: SLIP, CDIV, MTCH, ACATI rows, disclaimer
            self.assertEqual(len(activities), 2)

            by_symbol = {a.symbol: a for a in activities}
            self.assertEqual(by_symbol["ZETA"].action, "BUY")
            self.assertEqual(by_symbol["ZETA"].quantity, Decimal("116"))
            self.assertEqual(by_symbol["ZETA"].unit_price, Decimal("19.26"))

            self.assertEqual(by_symbol["HNST"].action, "SELL")
            self.assertEqual(by_symbol["HNST"].quantity, Decimal("1"))
            self.assertEqual(by_symbol["HNST"].unit_price, Decimal("3.66"))

    def test_parenthesized_negatives_stripped(self):
        """Robinhood Price shouldn't have parens, but Amount does for
        buys. The parser uses Price, so this really just tests that a
        trailing paren in the field doesn't trip up parsing."""
        csv = (
            '"Activity Date","Process Date","Settle Date","Instrument",'
            '"Description","Trans Code","Quantity","Price","Amount"\n'
            '"10/10/2025","10/10/2025","10/14/2025","ZETA","desc","Buy",'
            '"116","$19.26","($2,233.58)"\n'
        )
        with TemporaryDirectory() as tmp:
            p = _write(tmp, csv)
            a = list(parse_robinhood_csv(p, "acct"))
            self.assertEqual(a[0].unit_price, Decimal("19.26"))

    def test_multiline_description_preserved(self):
        """CUSIP lines in Description shouldn't break row parsing."""
        with TemporaryDirectory() as tmp:
            p = _write(tmp, ROBINHOOD_CSV)
            activities = list(parse_robinhood_csv(p, "acct"))
            self.assertEqual(len(activities), 2)  # unchanged count


# --- Dedup store ---

class DedupTests(unittest.TestCase):
    def test_idempotent(self):
        with TemporaryDirectory() as tmp:
            store = DedupStore(Path(tmp) / "d.sqlite")
            store.record("fp-1", "fidelity", "TSLA", "a")
            store.record("fp-1", "fidelity", "TSLA", "a")
            self.assertTrue(store.has("fp-1"))
            self.assertEqual(store.count(), 1)


# --- Date serialization ---

class DateSerializationTests(unittest.TestCase):
    def test_pacific_stays_same_day(self):
        from datetime import date
        s = serialize_date_as_local_noon(
            date(2026, 4, 15), resolve_tz("America/Los_Angeles")
        )
        self.assertTrue(s.startswith("2026-04-15T"))

    def test_invalid_tz_falls_back(self):
        from datetime import date
        s = serialize_date_as_local_noon(
            date(2026, 4, 15), resolve_tz("Not/Real")
        )
        self.assertEqual(s, "2026-04-15T12:00:00.000Z")


# --- Generic watcher (applies to both brokers) ---

class WatcherTests(unittest.TestCase):
    def test_routes_fidelity_subfolders(self):
        with TemporaryDirectory() as tmp:
            watch = Path(tmp) / "f-drop"
            store = DedupStore(Path(tmp) / "d.sqlite")
            client = MagicMock()
            client.create_order.return_value = {"id": "gf-1"}

            w = CsvDropWatcher(
                name="fidelity",
                watch_dir=watch,
                account_uuids={"mit": "uuid-mit", "link": "uuid-link"},
                parser=parse_fidelity_csv,
                currency="USD",
                client=client,
                store=store,
            )

            (watch / "mit").is_dir()
            (watch / "mit" / "processed").is_dir()
            (watch / "link").is_dir()

            (watch / "mit" / "a.csv").write_text(FIDELITY_CSV)
            _backdate(watch / "mit" / "a.csv")
            w.scan_once()

            # Each of the 2 imported activities should go to uuid-mit
            for call in client.create_order.call_args_list:
                self.assertEqual(call[0][0].account_id, "uuid-mit")
            self.assertEqual(client.create_order.call_count, 2)

    def test_routes_robinhood_subfolders(self):
        with TemporaryDirectory() as tmp:
            watch = Path(tmp) / "r-drop"
            store = DedupStore(Path(tmp) / "d.sqlite")
            client = MagicMock()
            client.create_order.return_value = {"id": "gf-1"}

            w = CsvDropWatcher(
                name="robinhood",
                watch_dir=watch,
                account_uuids={"mit-rh": "uuid-mit-rh"},
                parser=parse_robinhood_csv,
                currency="USD",
                client=client,
                store=store,
            )
            (watch / "mit-rh" / "a.csv").write_text(ROBINHOOD_CSV)
            _backdate(watch / "mit-rh" / "a.csv")
            w.scan_once()
            self.assertEqual(client.create_order.call_count, 2)

    def test_stray_file_not_processed(self):
        with TemporaryDirectory() as tmp:
            watch = Path(tmp) / "drop"
            store = DedupStore(Path(tmp) / "d.sqlite")
            client = MagicMock()
            w = CsvDropWatcher(
                name="fidelity", watch_dir=watch,
                account_uuids={"mit": "uuid"},
                parser=parse_fidelity_csv, currency="USD",
                client=client, store=store,
            )
            stray = watch / "wrong.csv"
            stray.write_text(FIDELITY_CSV)
            _backdate(stray)
            w.scan_once()
            self.assertEqual(client.create_order.call_count, 0)
            self.assertTrue(stray.exists())

    def test_dedup_across_scans(self):
        with TemporaryDirectory() as tmp:
            watch = Path(tmp) / "drop"
            store = DedupStore(Path(tmp) / "d.sqlite")
            client = MagicMock()
            client.create_order.return_value = {"id": "gf-1"}
            w = CsvDropWatcher(
                name="fidelity", watch_dir=watch,
                account_uuids={"mit": "uuid"},
                parser=parse_fidelity_csv, currency="USD",
                client=client, store=store,
            )

            f1 = watch / "mit" / "a.csv"
            f1.write_text(FIDELITY_CSV); _backdate(f1)
            w.scan_once()
            n = client.create_order.call_count

            f2 = watch / "mit" / "b.csv"
            f2.write_text(FIDELITY_CSV); _backdate(f2)
            w.scan_once()
            # No additional imports — same fingerprints
            self.assertEqual(client.create_order.call_count, n)

    def test_moves_on_failure(self):
        with TemporaryDirectory() as tmp:
            watch = Path(tmp) / "drop"
            store = DedupStore(Path(tmp) / "d.sqlite")
            client = MagicMock()
            client.create_order.return_value = {"id": "gf-1"}

            def broken_parser(path, account_id, currency):
                raise RuntimeError("simulated parser crash")

            w = CsvDropWatcher(
                name="fidelity", watch_dir=watch,
                account_uuids={"mit": "uuid"},
                parser=broken_parser, currency="USD",
                client=client, store=store,
            )
            f = watch / "mit" / "a.csv"
            f.write_text("whatever")
            _backdate(f)
            w.scan_once()
            self.assertFalse(f.exists())
            self.assertEqual(
                len(list((watch / "mit" / "failed").glob("*.csv"))), 1
            )


# --- Shortcut server ---

class ShortcutServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.store = DedupStore(Path(self.tmp.name) / "d.sqlite")
        self.client = MagicMock()
        self.client.create_order.return_value = {"id": "gf-id"}

        self.server = ShortcutServer(
            port=_find_free_port(),
            auth_token="s3cret",
            account_map={"brokerage-fidelity": "uuid-fid"},
            currency="USD",
            client=self.client,
            store=self.store,
        )
        self.server.run_in_thread()
        time.sleep(0.2)

    def tearDown(self):
        self.tmp.cleanup()

    def _post(self, body, token="s3cret"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.server.port}/trade",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Auth-Token": token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_success(self):
        status, body = self._post({
            "account": "brokerage-fidelity",
            "symbol": "tsla", "action": "buy",
            "quantity": 3, "unit_price": 245.10,
            "date": "2026-04-15",
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["imported"])
        a = self.client.create_order.call_args[0][0]
        self.assertEqual(a.symbol, "TSLA")
        self.assertEqual(a.account_id, "uuid-fid")

    def test_unauthorized(self):
        status, _ = self._post({"account": "x"}, token="wrong")
        self.assertEqual(status, 401)

    def test_unknown_account(self):
        status, body = self._post({
            "account": "unknown", "symbol": "X", "action": "BUY",
            "quantity": 1, "unit_price": 1,
        })
        self.assertEqual(status, 400)
        self.assertIn("unknown account", body["error"])


if __name__ == "__main__":
    unittest.main()
