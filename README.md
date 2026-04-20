# ghostfolio-importer

## Overview

A self-hosted Python service that keeps a Ghostfolio instance in sync with brokerage transactions. Runs as a Docker container on Proxmox/Dockge. Application code lives on a Synology NAS; drop folders are also NAS-mounted so you can drag-and-drop CSVs from any device over SMB.

Three ingestion paths feed into the same canonical pipeline:
- **Fidelity** — drop single-account CSVs into per-account subfolders
- **Robinhood** — drop Account Activity CSVs into per-account subfolders
- **Manual** — CLI helper for historical trades or ACAT transfers without cost basis

All paths share SHA-256 fingerprint-based idempotency, so re-uploading a CSV is always safe.

---

## Repository layout

```
ghostfolio-importer/
├── app/
│   ├── activity.py         # Canonical Activity dataclass + fingerprint
│   ├── config.py           # Env-driven config; broker-tagged ACCOUNT_MAP
│   ├── dedup.py            # SQLite idempotency store
│   ├── dedup_cli.py        # CLI for inspecting/managing the dedup store
│   ├── fidelity.py         # Fidelity CSV parser (BUY/SELL only)
│   ├── ghostfolio.py       # HTTP client; TZ-safe date serialization
│   ├── import_manual.py    # CLI for historical/ACAT imports
│   ├── list_accounts.py    # CLI to discover Ghostfolio account UUIDs
│   ├── main.py             # Entry point; wires up all watchers and servers
│   ├── parsing.py          # Shared money/qty/date helpers
│   ├── robinhood.py        # Robinhood CSV parser (Buy/Sell only)
│   ├── shortcut_server.py  # HTTP endpoint for iOS shortcut
│   └── watcher.py          # Generic subfolder drop-folder watcher
├── tests/
│   ├── fixtures.py                 # Real CSV snippets from both brokers
│   ├── test_date_serialization.py  # TZ-safe date tests
│   └── test_pipeline.py            # Full pipeline (27 tests)
├── Dockerfile              # Only used when NOT mounting code from NAS
├── compose.yaml            # NAS-mount version (production)
├── requirements.txt        # httpx, apscheduler, robin-stocks, pyotp
└── .env.example            # All config options documented
```

---

## Infrastructure

| Component | Where it runs |
|---|---|
| Ghostfolio app | Proxmox container, Dockge stack `ghostfolio`, port 3333 |
| Ghostfolio Postgres | Same stack, named volume |
| ghostfolio-importer | Proxmox container, Dockge stack `ghostfolio-importer`, port 8421 |
| App code | Synology NAS: `/synology-storage/dockge/ghostfolio-importer/` |
| Fidelity drop | Synology NAS: `.../fidelity-drop/<account-key>/` |
| Robinhood drop | Synology NAS: `.../robinhood-drop/<account-key>/` |
| Dedup SQLite | Docker named volume `ghostfolio-importer_importer-state:/state` |

---

## Configuration (.env)

### Required

| Variable | Example | Purpose |
|---|---|---|
| `GHOSTFOLIO_URL` | `http://192.168.1.2:3333` | Ghostfolio base URL. Use host IP, not service name (different Docker network) |
| `GHOSTFOLIO_TOKEN` | `abc123...` | Ghostfolio security token (Profile → Show security token) |
| `ACCOUNT_MAP` | see below | Per-account UUID and broker tag |
| `HTTP_TOKEN` | `openssl rand -hex 24` | Shared secret for iOS shortcut endpoint |
| `APP_PATH` | `/synology-storage/dockge/ghostfolio-importer` | NAS path where app code lives |
| `FIDELITY_DROP_PATH` | `.../fidelity-drop` | NAS path for Fidelity CSV drops |
| `ROBINHOOD_DROP_PATH` | `.../robinhood-drop` | NAS path for Robinhood CSV drops |

### Optional

| Variable | Default | Purpose |
|---|---|---|
| `DEFAULT_CURRENCY` | `USD` | Currency for all imported activities |
| `TZ` | `UTC` | IANA timezone (e.g. `America/Los_Angeles`). Prevents UTC-midnight date drift in UI |
| `MANUAL_SYMBOLS` | _(empty)_ | Comma-separated tickers to use `MANUAL` data source (for delisted stocks, e.g. `TRCH`) |
| `HTTP_EXTERNAL_PORT` | `8421` | Host port for the iOS shortcut HTTP endpoint |
| `HTTP_PORT` | `8080` | Container-internal port (don't change) |
| `FIDELITY_WATCH_DIR` | `/fidelity-drop` | Container path for Fidelity drops (matches compose volume) |
| `ROBINHOOD_WATCH_DIR` | `/robinhood-drop` | Container path for Robinhood drops (matches compose volume) |
| `DB_PATH` | `/state/dedup.sqlite` | Path to dedup SQLite file |
| `LOG_LEVEL` | `INFO` | Python logging level |

### ACCOUNT_MAP format

```
key=uuid:broker,key2=uuid2:broker2,...
```

- `key` — friendly name used as subfolder name and in iOS shortcut
- `uuid` — Ghostfolio account UUID (get via `python -m app.list_accounts`)
- `broker` — `fidelity`, `robinhood`, or `manual`

Broker determines which watcher auto-creates subfolders:
- `fidelity` → subfolder under `FIDELITY_DROP_PATH`
- `robinhood` → subfolder under `ROBINHOOD_DROP_PATH`
- `manual` → no subfolder; only accessible via iOS shortcut or `import_manual`

---

## Drop folder structure

On first start, the importer auto-creates subfolders for every account:

```
fidelity-drop/
├── brokerage-fidelity/
│   ├── *.csv            ← drop Fidelity CSVs here
│   ├── processed/       ← auto-moved on success
│   └── failed/          ← auto-moved on parse error
└── brokerage-link/
    └── ...

robinhood-drop/
├── brokerage/
├── joint-investment/
├── roth-ira/
└── traditional-ira/
```

Files dropped in the **root** of either folder (not in a subfolder) are logged as "stray" and left untouched.

---

## Broker CSV formats

### Fidelity

**How to export**: Fidelity.com → select account → Activity & Orders → Download transactions

**Format**: Single-account export (no account identifier in file — routing is by subfolder name)

```
Run Date,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),
Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date
```

**What's imported**:
- `YOU BOUGHT ...` → `BUY`
- `YOU SOLD ...` → `SELL`

**What's skipped**: `DIVIDEND RECEIVED`, `REINVESTMENT`, `TRANSFERRED FROM/TO`, interest, fees. Dividends are tracked as cash in your brokerage but not as position changes, so they don't affect investment growth tracking.

**Known quirks handled**:
- 0–N disclaimer/preamble lines before header
- Negative quantity on SELL rows (taken as absolute value)
- Empty fee cells (not `0.00`)
- Footer disclaimer rows with fewer columns than header

### Robinhood

**How to export**: Robinhood app → Account → Statements → Account Statements → select range → download CSV

**Format**:
```
"Activity Date","Process Date","Settle Date","Instrument","Description",
"Trans Code","Quantity","Price","Amount"
```

**What's imported**:

| Trans Code | Action | Notes |
|---|---|---|
| `Buy` | BUY | Standard stock purchase |
| `Sell` | SELL | Standard stock sale |

**What's skipped silently**:

| Trans Code | Meaning |
|---|---|
| `CDIV` | Cash dividend (no DRIP — cash deposited, no shares) |
| `SLIP` | Stock Lending Income Program (cash) |
| `MTCH` | IRA Match interest (cash) |
| `SPL` | Stock split — Ghostfolio handles via Yahoo automatically |
| `RTP` | SPAC redemption (cash) |
| `GMPC` | Robinhood Gold payment (cash fee) |
| `BCXL` | Buy cancellation / order correction |
| `MISC` | Miscellaneous cash adjustment |
| `ACH`, `AFEE`, `DFEE`, `GOLD`, `SPR`, `REC`, `TAX`, `WITH`, `INT` | Various cash/admin events |

**What generates a WARNING log**:

| Trans Code | Meaning | Action needed |
|---|---|---|
| `ACATI` | ACAT transfer in (shares received, no cost basis) | Use `import_manual` with original purchase prices |
| `ACATO` | ACAT transfer out | No import needed |

**Known quirks handled**:
- Multi-line `Description` field (CUSIP on second line) — handled by Python csv module
- Dollar-prefixed prices: `$19.26`, `($2,233.58)` — parentheses stripped, absolute value taken
- Trailing disclaimer row — detected by empty `Trans Code` field

---

## Dedup system

Every activity generates a SHA-256 fingerprint of:
```
account_id|symbol|date|action|quantity|unit_price
```

Before POSTing to Ghostfolio, the importer checks the local SQLite store. If the fingerprint exists, the row is skipped. After a successful POST, the fingerprint is recorded.

This means:
- Re-uploading a CSV is always safe
- The same trade reported by two sources (e.g. shortcut + CSV) only imports once
- If Ghostfolio rejects a row, the fingerprint is NOT recorded → it will be retried next time the CSV is dropped

### Dedup CLI

```bash
# See recent imports
docker compose exec importer python -m app.dedup_cli list
docker compose exec importer python -m app.dedup_cli list --source robinhood

# Count by source
docker compose exec importer python -m app.dedup_cli count

# Delete a fingerprint (retry a failed row)
docker compose exec importer python -m app.dedup_cli delete <fingerprint>

# Delete all records for a source (triggers full re-import)
docker compose exec importer python -m app.dedup_cli delete --source fidelity
```

---

## Date handling

Ghostfolio stores dates as UTC. Without adjustment, a trade on April 15 stored as UTC midnight displays as April 14 in a Pacific-time browser.

Fix: dates are serialized as **noon in your local timezone** converted to UTC. This keeps the display date stable across all timezones from UTC-11 to UTC+11.

Set `TZ=America/Los_Angeles` in `.env`.

---

## Delisted / unresolvable symbols

Ghostfolio validates each symbol against Yahoo Finance on import. For delisted tickers that Yahoo no longer carries, add them to `MANUAL_SYMBOLS`:

```bash
MANUAL_SYMBOLS=TRCH,CLVS
```

These symbols will use `MANUAL` data source instead of `YAHOO`. No live price feed, but trade history is preserved for cost-basis tracking.

**Additional step required in Ghostfolio**: After importing, go to Admin → Market Data → find the symbol → add at least one price entry (use the last known trading price or $0 for fully delisted stocks). Without a price entry, SELL activities against MANUAL symbols will be rejected.

---

## Manual import (historical trades & ACAT transfers)

For trades that brokers can't export (>5 years old) or ACAT-transferred shares without cost basis in the CSV.

**CSV format**:
```csv
account_key,date,symbol,action,quantity,unit_price,fee
brokerage-fidelity,2020-09-23,TSLA,BUY,9,43.33,0
```

**Usage**:
```bash
# Dry run (no API calls)
docker compose exec importer python -m app.import_manual --dry-run /fidelity-drop/trades.csv

# Actual import
docker compose exec importer python -m app.import_manual /fidelity-drop/trades.csv
```

Place the file somewhere the container can see (e.g. root of `/fidelity-drop/` — the watcher only picks up files inside account subfolders, so root is safe for staging).

**TSLA stock split note**: TSLA did a 3-for-1 split on 2022-08-25. Lots purchased before this date need split-adjusted quantities and prices:
- New quantity = original × 3
- New price = original ÷ 3

---

## iOS Shortcut

The importer exposes a POST endpoint for logging trades from your phone.

**Endpoint**: `http://<host-ip>:8421/trade`  
**Auth**: `X-Auth-Token: <HTTP_TOKEN>`

**Request body**:
```json
{
  "account": "brokerage-fidelity",
  "symbol": "TSLA",
  "action": "BUY",
  "quantity": 3,
  "unit_price": 245.10,
  "date": "2026-04-15",
  "fee": 0
}
```

`date` is optional (defaults to today). `fee` is optional (defaults to 0).

**Response**: `{"imported": true, "fingerprint": "abc123..."}` or `{"imported": false, ...}` if duplicate.

**Build the Shortcut** (Shortcuts app → New):
1. Ask for Input → Account (text, default: your most-used account key)
2. Ask for Input → Symbol (text)
3. Ask for Input → Action (text, default: `buy`)
4. Ask for Input → Quantity (number, decimal allowed)
5. Ask for Input → Unit price (number, decimal allowed)
6. Dictionary → build JSON from the above variables
7. Get Contents of URL → POST to `http://<host>:8421/trade`, header `X-Auth-Token`, body as JSON
8. Get Dictionary Value → `imported` from result
9. If imported = 1 → Show Notification "Trade recorded" / else "Duplicate — already recorded"

---

## Operations runbook

### Restart after code change

```bash
docker compose restart importer
docker compose logs -f importer
```

### View logs

```bash
docker compose logs -f importer
docker compose logs importer | grep -iE 'imported|failed|stray|WARNING|ERROR'
```

### Re-import a processed CSV

```bash
mv /synology-storage/.../fidelity-drop/brokerage-fidelity/processed/2026*.csv \
   /synology-storage/.../fidelity-drop/brokerage-fidelity/
```

Already-imported rows are deduped; only new rows will POST to Ghostfolio.

### Discover Ghostfolio account UUIDs

```bash
docker compose exec importer python -m app.list_accounts
```

### Run tests

```bash
docker compose exec importer python -m unittest discover tests
```

---

## What is NOT implemented

| Feature | Notes |
|---|---|
| **Robinhood auto-poll** | Passkey-only Robinhood accounts have no unofficial API support. Manual CSV export required. |
| **Fidelity auto-pull** | No public Fidelity API for retail accounts. Manual CSV export required. |
| **Dividend tracking** | Fidelity dividends/reinvestments are skipped (cash only, not position changes). Robinhood CDIV skipped (no DRIP). Ghostfolio pulls dividend history from Yahoo for informational purposes but doesn't affect your imported positions. |
| **HSA Bank** | Tagged as `manual` in ACCOUNT_MAP. HSA trades are infrequent enough for iOS shortcut entry. |
| **Robinhood IRA auto-import** | Same as Robinhood above — manual CSV export. |
| **Options** | Not handled; all Robinhood option trans codes are skipped. |
| **Crypto** | Robinhood Crypto is in a separate CSV/system not covered. |
| **Stock splits** | Ghostfolio handles forward splits automatically via Yahoo. Reverse splits (SPR) are in the skip list. Historical lots entered before a split need manual price/quantity adjustment. |
| **Wash sales** | Not tracked. Tax-loss harvesting scenarios are not modeled. |
| **Multi-currency accounts** | All accounts assumed USD. Non-USD stocks (e.g. Canadian, London-listed) would need per-account currency config. |
| **Ghostfolio network name resolution** | `GHOSTFOLIO_URL` must use host IP, not service name `ghostfolio`. Both stacks are on separate Docker networks. Can be fixed by joining the `ghostfolio_default` network in `compose.yaml`. |
| **Metrics / alerting** | No Prometheus endpoint. No notification on import failure beyond container logs. |
| **Web UI for dedup** | Dedup management is CLI-only. |

---

## Migration to NAS (current setup)

The application code is served from the NAS rather than baked into the Docker image. This means:

- **Edit code**: open files over SMB from any device
- **Apply changes**: `docker compose restart importer` (~5 seconds, no rebuild)
- **No SSH required** for routine maintenance

The trade-off vs. a baked image:
- First startup is slower (~30-60s for pip install; subsequent starts are fast due to `pip-cache` named volume)
- Upstream dep changes could affect the running container (mitigated by pinned versions in `requirements.txt`)

