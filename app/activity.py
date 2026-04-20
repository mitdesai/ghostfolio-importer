"""The canonical Activity type that all ingestion modules produce."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

ActionType = Literal["BUY", "SELL", "DIVIDEND"]


@dataclass(frozen=True)
class Activity:
    """A single transaction to import into Ghostfolio."""
    account_id: str
    symbol: str
    data_source: str
    currency: str
    date: date
    action: ActionType
    quantity: Decimal
    unit_price: Decimal
    fee: Decimal = Decimal("0")
    source: str = ""  # "fidelity"/"robinhood"/"shortcut"/"manual"

    def fingerprint(self) -> str:
        """Stable hash. Includes action so BUY and DIVIDEND on the same
        day + symbol + amount are distinct.
        """
        payload = "|".join([
            self.account_id,
            self.symbol,
            self.date.isoformat(),
            self.action,
            f"{self.quantity:.8f}",
            f"{self.unit_price:.8f}",
        ])
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
