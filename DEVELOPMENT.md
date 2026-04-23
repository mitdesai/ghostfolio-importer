# Development Guide

Implementation details, data models, and extension points for ghostfolio-importer. For deployment, configuration, and operations, see [README.md](README.md).

---

## Repository layout

```
app/
├── activity.py          # Canonical Activity dataclass + SHA-256 fingerprint
├── config.py            # Config dataclass, ACCOUNT_MAP parser, AccountInfo
├── dedup.py             # DedupStore (SQLite, thread-safe)
├── dedup_cli.py         # CLI for inspecting/managing the dedup store
├── fidelity.py          # Fidelity CSV parser (BUY/SELL only)
├── ghostfolio.py        # GhostfolioClient (httpx, JWT re-auth, date serialization)
├── import_manual.py     # CLI for historical/ACAT imports
├── list_accounts.py     # CLI to discover Ghostfolio account UUIDs
├── main.py              # Entry point: wires watchers + HTTP server + signals
├── parsing.py           # Shared money/qty/date helpers (clean_money, clean_quantity, parse_date)
├── robinhood.py         # Robinhood CSV parser (Buy/Sell only)
├── shortcut_server.py   # HTTP server: /trade, /snapshot, /snapshot/pdf, /health
├── snapshot.py          # fetch_snapshot(): Ghostfolio API → PortfolioSnapshot dataclass
├── snapshot_template.py # HTML renderer (f-string template, no template engine)
└── watcher.py           # CsvDropWatcher: poll loop, subfolder routing, move-on-done
tests/
├── fixtures.py          # Real CSV snippets from Fidelity and Robinhood
├── test_date_serialization.py  # TZ-safe date serialization tests
└── test_pipeline.py     # 27 integration tests (config, parsers, watcher, shortcut)
tools/
└── preview_snapshot.py  # Render snapshot dashboard with mock data (no Ghostfolio needed)
```

---

## Architecture overview

`main.py` starts three daemon threads and then blocks on a `threading.Event` waiting for SIGTERM/SIGINT:

| Thread | Name | What it runs |
|---|---|---|
| HTTP server | `http` | `ShortcutServer.run_forever()` → `ThreadingHTTPServer` serving `/health`, `/trade` (auth required), `/snapshot`, `/snapshot/pdf` (no auth) |
| Fidelity watcher | `fidelity` | `CsvDropWatcher.run_forever()` with `parse_fidelity_csv` — polls every 60s |
| Robinhood watcher | `robinhood` | `CsvDropWatcher.run_forever()` with `parse_robinhood_csv` — polls every 60s |

All threads share:
- One `GhostfolioClient` instance (httpx-based, with JWT re-auth)
- One `DedupStore` instance (SQLite with `threading.Lock` for writes)

Threads are disabled if their prerequisites are missing:
- HTTP server disabled if `HTTP_TOKEN` is empty
- Fidelity watcher disabled if no `fidelity` accounts in `ACCOUNT_MAP`
- Robinhood watcher disabled if no `robinhood` accounts in `ACCOUNT_MAP`

---

## Data flow: CSV import

```
File appears in <watch_dir>/<account-key>/*.csv
  │
  ▼
CsvDropWatcher.scan_once()
  │  skip if mtime < 3 seconds ago (partial write guard)
  ▼
parser(path, account_id, currency) → Iterator[Activity]
  │  fidelity.py or robinhood.py; non-BUY/SELL rows skipped at parse time
  ▼
For each Activity:
  │
  ├─ Activity.fingerprint()
  │    SHA-256 of "account_id|symbol|YYYY-MM-DD|action|qty:.8f|price:.8f"
  │    First 16 hex chars
  │
  ├─ DedupStore.has(fingerprint)?
  │    yes → skip (debug log)
  │    no  ↓
  │
  ├─ GhostfolioClient.create_order(activity)
  │    POST /api/v1/order
  │    date serialized as local noon UTC
  │    MANUAL_SYMBOLS → data_source overridden to "MANUAL"
  │
  ├─ DedupStore.record(fingerprint, source, symbol, account_id, ghostfolio_id)
  │
  ▼
File moved to processed/ (success) or failed/ (parse exception)
```

---

## Data flow: portfolio snapshot

```
GET /snapshot (or /snapshot/pdf)
  │
  ▼
fetch_snapshot(client, currency)
  │
  ├─ GET /api/v1/account → list of {id, name, currency, ...}
  │
  ├─ GET /api/v1/portfolio/details?range=max → overall holdings + summary
  │
  ├─ For each account:
  │    GET /api/v1/portfolio/details?range=max&accounts=<id>
  │    → per-account holdings
  │
  ├─ classify_account(name) for each account:
  │    "roth" in name → Roth IRA
  │    "ira" in name  → Traditional IRA
  │    otherwise      → Regular Brokerage
  │
  ├─ Build HoldingSummary per symbol (from overall response)
  │    Attach AccountHolding entries (from per-account responses)
  │
  ├─ Build AccountTypeSummary buckets
  │    Sort holdings by value descending
  │
  ▼
PortfolioSnapshot dataclass
  │
  ├─ render_html(snapshot) → HTML string (f-string template)
  │
  ├─ (if /snapshot/pdf) WeasyHTML(string=html).write_pdf() → PDF bytes
  │
  ▼
HTTP response
```

**N+1 pattern**: With N Ghostfolio accounts, the snapshot makes N+2 API calls (1 account list + 1 overall + N per-account). This is necessary because Ghostfolio's `/portfolio/details` endpoint returns holdings aggregated across all accounts — the only way to get per-account holdings is to filter by account ID. With 7 accounts: 9 sequential HTTP calls, typically 2–5 seconds on a local network.

---

## Data models

### Activity (`app/activity.py`)

The canonical transaction record shared by all ingestion paths.

| Field | Type | Source |
|---|---|---|
| `account_id` | `str` | Ghostfolio UUID from ACCOUNT_MAP |
| `symbol` | `str` | Ticker, uppercased by parser |
| `data_source` | `str` | Always `"YAHOO"`; overridden to `"MANUAL"` at POST time for MANUAL_SYMBOLS |
| `currency` | `str` | From `DEFAULT_CURRENCY` (always `"USD"` in current setup) |
| `date` | `date` | Trade date |
| `action` | `Literal["BUY", "SELL", "DIVIDEND"]` | Parsers only emit BUY/SELL currently |
| `quantity` | `Decimal` | Always positive (absolute value at parse time) |
| `unit_price` | `Decimal` | Per-share price |
| `fee` | `Decimal` | Defaults to `0` |
| `source` | `str` | `"fidelity"`, `"robinhood"`, `"shortcut"`, or `"manual"` |

`Activity.fingerprint()` returns the first 16 hex chars of SHA-256 over `account_id|symbol|date|action|quantity|unit_price` (quantity and unit_price formatted to 8 decimal places).

### AccountInfo (`app/config.py`)

| Field | Type | Notes |
|---|---|---|
| `key` | `str` | Friendly name, subfolder name |
| `uuid` | `str` | Ghostfolio account UUID |
| `broker` | `Literal["fidelity", "robinhood", "manual"]` | Determines which watcher handles this account |

### PortfolioSnapshot (`app/snapshot.py`)

Top-level container for a rendered report.

| Field | Type | Source |
|---|---|---|
| `report_date` | `date` | `date.today()` |
| `total_value` | `float` | `summary.currentValue` or `summary.netWorth` from Ghostfolio |
| `total_investment` | `float` | `summary.totalInvestment` from Ghostfolio |
| `total_gain_loss` | `float` | Computed: `total_value - total_investment` |
| `total_gain_loss_pct` | `float` | Computed: `total_gain_loss / total_investment * 100` |
| `holdings` | `list[HoldingSummary]` | Sorted by value descending |
| `account_type_sections` | `list[AccountTypeSummary]` | Roth IRA, Traditional IRA, Regular Brokerage |
| `currency` | `str` | From `DEFAULT_CURRENCY` |

### HoldingSummary (`app/snapshot.py`)

One stock aggregated across all accounts.

| Field | Type | Ghostfolio API field |
|---|---|---|
| `symbol` | `str` | `assetProfile.symbol` or key |
| `name` | `str` | `assetProfile.name` or key |
| `currency` | `str` | `assetProfile.currency` |
| `total_quantity` | `float` | `quantity` |
| `total_investment` | `float` | `investment` (total cost basis) |
| `market_price` | `float` | `marketPrice` |
| `total_value` | `float` | `valueInBaseCurrency` |
| `gross_performance` | `float` | `grossPerformance` |
| `gross_performance_pct` | `float` | `grossPerformancePercent` |
| `net_performance` | `float` | `netPerformance` |
| `net_performance_pct` | `float` | `netPerformancePercent` |
| `allocation_pct` | `float` | `allocationInPercentage` or computed |
| `account_holdings` | `list[AccountHolding]` | Built from per-account API calls |

**Computed property**: `avg_price` = `total_investment / total_quantity`

### AccountHolding (`app/snapshot.py`)

One stock in one specific account.

| Field | Type | Notes |
|---|---|---|
| `account_id` | `str` | Ghostfolio account UUID |
| `account_name` | `str` | From `/api/v1/account` response |
| `account_type` | `str` | Classified from account name |
| `symbol` | `str` | Ticker |
| `name` | `str` | Company name |
| `quantity` | `float` | Shares in this account |
| `investment` | `float` | Cost basis in this account |
| `market_price` | `float` | Current price |
| `value` | `float` | Current value in this account |
| `gross_performance` | `float` | Account-scoped |
| `gross_performance_pct` | `float` | Account-scoped |
| `net_performance` | `float` | Account-scoped |
| `net_performance_pct` | `float` | Account-scoped |
| `currency` | `str` | — |

### AccountTypeSummary (`app/snapshot.py`)

| Field | Type | Notes |
|---|---|---|
| `account_type` | `str` | `"Roth IRA"`, `"Traditional IRA"`, or `"Regular Brokerage"` |
| `total_value` | `float` | Sum of all holdings in this type |
| `holdings` | `list[AccountHolding]` | Sorted by value descending |

**Property**: `tax_note` returns a one-line tax implication string per account type.

---

## Ghostfolio auth flow

`GhostfolioClient` (`app/ghostfolio.py`) handles authentication automatically:

1. On first API call: `POST /api/v1/auth/anonymous` with `{"accessToken": GHOSTFOLIO_TOKEN}` → receives `{"authToken": "<JWT>"}`
2. All subsequent requests include `Authorization: Bearer <JWT>`
3. On 401 response: clears stored JWT, re-authenticates, retries the request once

The `GHOSTFOLIO_TOKEN` is the static "security token" from Ghostfolio's Profile page. The JWT has a limited lifespan but the re-auth-on-401 handles expiry without requiring a service restart.

---

## Adding a new broker

1. **Create `app/<broker>.py`** with a parser function:
   ```python
   def parse_<broker>_csv(path: Path, account_id: str, default_currency: str) -> Iterator[Activity]:
   ```
   This signature matches `ParserFn` defined in `watcher.py`.

2. **Parser contract**:
   - Yield `Activity(source="<broker>", ...)` for BUY/SELL rows
   - Skip non-BUY/SELL rows silently or with `log.debug()`
   - Log `WARNING` for rows that need user action (e.g. ACAT transfers)
   - Use `clean_money()` and `clean_quantity()` from `parsing.py` — they strip `$`, commas, parentheses
   - Use `parse_date()` from `parsing.py` — it handles multiple date formats
   - Always take absolute value of quantity (sign is conveyed by the action field)

3. **Update `app/config.py`**:
   - Add broker name to the `Broker` literal type
   - Add it to the validation set in `_parse_account_map()`
   - Add `<broker>_watch_dir: Path` to the `Config` dataclass
   - Add the env var to `load_config()`

4. **Update `app/main.py`**: Add a watcher block mirroring the fidelity/robinhood pattern:
   ```python
   broker_accounts = accounts_by_broker(cfg.accounts, "<broker>")
   if broker_accounts:
       watcher = CsvDropWatcher(name="<broker>", watch_dir=cfg.<broker>_watch_dir, ...)
       t = threading.Thread(target=watcher.run_forever, daemon=True, name="<broker>")
       t.start()
       threads.append(t)
   ```

5. **Update `.env.example`**: Add the new watch dir and example ACCOUNT_MAP entries.

6. **Add tests**: Add fixture data to `tests/fixtures.py` and parser tests to `tests/test_pipeline.py` following the existing `FidelityParserTests`/`RobinhoodParserTests` pattern.

---

## Docker and WeasyPrint

Two deployment modes exist:

### Production: compose.yaml (NAS-mounted code)

Uses `python:3.12-slim` base image. The `command` installs both system packages (for WeasyPrint PDF rendering) and pip packages at startup:

```yaml
command: >
  sh -c "apt-get update && apt-get install -y --no-install-recommends
  libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0
  libffi-dev shared-mime-info fonts-dejavu-core
  && rm -rf /var/lib/apt/lists/*
  && pip install -q -r requirements.txt
  && python -m app.main"
```

First startup is slower (~30–60s for apt + pip). Subsequent restarts are faster thanks to the `pip-cache` named volume, though apt packages are reinstalled each time.

### Dockerfile (standalone image)

System packages are baked into the image at build time. Used when NOT mounting code from NAS.

Required apt packages for WeasyPrint:

| Package | Purpose |
|---|---|
| `libpango-1.0-0` | Text layout engine |
| `libpangocairo-1.0-0` | Pango/Cairo integration |
| `libcairo2` | 2D graphics library |
| `libgdk-pixbuf-2.0-0` | Image loading |
| `libffi-dev` | Foreign function interface (cffi dependency) |
| `shared-mime-info` | MIME type database |
| `fonts-dejavu-core` | Default fonts for rendered text |

Without these packages, `pip install weasyprint` succeeds but PDF rendering fails at runtime with missing library errors.

---

## Dedup store internals

SQLite schema (`app/dedup.py`):

```sql
CREATE TABLE IF NOT EXISTS imported (
    fingerprint   TEXT PRIMARY KEY,
    source        TEXT NOT NULL,      -- fidelity / robinhood / shortcut / manual
    symbol        TEXT NOT NULL,
    account_id    TEXT NOT NULL,
    imported_at   TEXT NOT NULL,      -- UTC ISO-8601
    ghostfolio_id TEXT                -- NULL if Ghostfolio didn't return an id
);
CREATE INDEX IF NOT EXISTS idx_imported_source ON imported(source);
CREATE INDEX IF NOT EXISTS idx_imported_symbol ON imported(symbol);
```

**Thread safety**: All `has()` and `record()` calls are serialized through a `threading.Lock`. Each operation opens and closes its own `sqlite3` connection (not a connection pool). The lock ensures that concurrent watcher threads and HTTP server threads don't corrupt the database.

**Why local dedup instead of querying Ghostfolio**: (1) Different sources may report the same trade with slightly different rounding — local fingerprinting gives control over "same" semantics. (2) Avoids an API call per activity just to check existence. (3) Makes re-runs completely safe.

---

## Testing

### Running tests

```bash
# In-container
docker compose exec importer python -m pytest tests/ -v

# Locally (requires httpx installed)
pip install httpx
python -m pytest tests/ -v
```

### What's covered (27 tests)

| Test class | What it verifies |
|---|---|
| `ConfigTests` | ACCOUNT_MAP parsing, missing broker defaults, unknown broker fallback, broker filtering |
| `FidelityParserTests` | BUY/SELL extraction, skip logic, preamble detection, short-row guard |
| `RobinhoodParserTests` | BUY/SELL extraction, parenthesized negatives, multi-line description |
| `DedupTests` | Idempotent re-import (second import returns `False`) |
| `DateSerializationTests` | UTC noon stays on correct day for Pacific/Eastern/Tokyo, invalid TZ fallback |
| `WatcherTests` | Subfolder routing, stray file skipping, dedup across scans, file move to `failed/` |
| `ShortcutServerTests` | Successful trade, 401 on bad token, unknown account rejection |

### What's NOT covered

- **Snapshot feature**: `fetch_snapshot()`, `render_html()`, and the `/snapshot` endpoints have no automated tests. Testing would require either a live Ghostfolio instance or detailed mocking of the multi-call API pattern.
- **WeasyPrint PDF rendering**: Not exercised in tests.
- **End-to-end with real Ghostfolio**: Tests stub the `GhostfolioClient` — no actual HTTP calls to Ghostfolio.

---

## Dev tools

### `tools/preview_snapshot.py`

Renders the snapshot dashboard HTML using mock data — no running Ghostfolio instance or Docker container needed. Useful for iterating on the template design locally.

```bash
# Full dashboard with account details (default) — opens in browser
python tools/preview_snapshot.py

# Summary mode — no per-account breakdowns (matches "PDF Summary" output)
python tools/preview_snapshot.py --no-details

# Generate both versions side by side
python tools/preview_snapshot.py --both

# Write to a specific file instead of a temp file
python tools/preview_snapshot.py --out /tmp/snapshot.html
```

The mock data includes 9 holdings across 3 account types (Roth IRA, Traditional IRA, Regular Brokerage) with multiple brokerage accounts per holding. Edit `_build_mock_data()` to adjust symbols, quantities, or account structure.

---

## Known limitations

| Limitation | Details |
|---|---|
| **Snapshot N+1 API calls** | `fetch_snapshot()` makes one API call per account. Ghostfolio has no bulk per-account endpoint. Scales linearly with account count. |
| **GhostfolioClient thread safety** | A single `httpx.Client` is shared across all threads. Concurrent requests are rare in practice (watchers poll every 60s, HTTP endpoint is low-traffic) but the JWT re-auth path could theoretically race. |
| **Unused dependencies** | `apscheduler` and `robin-stocks` are in `requirements.txt` but unused in current code (remnants of a Robinhood API polling experiment). They add startup time and image size. |
| **Duplicate client methods** | `GhostfolioClient` has both `list_accounts()` (used by the `list_accounts` CLI) and `get_accounts()` (used by `fetch_snapshot()`). Both call `GET /api/v1/account`. |
| **No snapshot tests** | See Testing section above. |
| **Apt packages on every restart** | The compose.yaml deployment reinstalls apt packages on each container restart since the base image is ephemeral. Could be fixed by building a custom image or using a Docker volume for `/var/cache/apt`. |
