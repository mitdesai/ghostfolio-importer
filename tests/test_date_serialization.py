"""Verify date serialization never drifts to the wrong day across timezones.

This is a pure-function test (doesn't touch httpx/networking) so it runs
in any environment.
"""
import sys
import types
import unittest
from datetime import date

# httpx may not be installed in every test environment; stub it so the
# import of app.ghostfolio works.
if "httpx" not in sys.modules:
    stub = types.ModuleType("httpx")
    stub.Client = object
    stub.HTTPError = Exception
    stub.Response = object
    sys.modules["httpx"] = stub

from app.ghostfolio import resolve_tz, serialize_date_as_local_noon


class DateSerializationTests(unittest.TestCase):
    def _s(self, tz_name, d=date(2026, 4, 15)):
        return serialize_date_as_local_noon(d, resolve_tz(tz_name))

    def test_pacific_stays_on_same_day(self):
        # User's case: Fresno (PDT/PST). Trade on April 15 should display
        # as April 15 regardless of daylight saving status.
        self.assertTrue(self._s("America/Los_Angeles").startswith("2026-04-15T"))

    def test_pacific_pst_winter(self):
        # January = PST (UTC-8). Still April-style safety.
        s = serialize_date_as_local_noon(
            date(2026, 1, 15), resolve_tz("America/Los_Angeles")
        )
        self.assertTrue(s.startswith("2026-01-15T"), s)

    def test_utc_noon_is_exact(self):
        self.assertEqual(self._s("UTC"), "2026-04-15T12:00:00.000Z")

    def test_eastern(self):
        self.assertTrue(self._s("America/New_York").startswith("2026-04-15T"))

    def test_tokyo(self):
        # Tokyo is UTC+9. Noon local = 03:00 UTC same calendar day.
        self.assertTrue(self._s("Asia/Tokyo").startswith("2026-04-15T"))

    def test_invalid_tz_falls_back_to_utc(self):
        self.assertEqual(self._s("Not/Real"), "2026-04-15T12:00:00.000Z")


if __name__ == "__main__":
    unittest.main()
