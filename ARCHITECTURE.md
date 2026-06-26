# Math Finance Simulator — Architecture

## Overview
A classroom stock market simulation built with NiceGUI, Google OAuth, Yahoo Finance data, and Google Cloud Storage persistence. Students trade fictional portfolios with $1k starting cash (100,000¢) and $100/week deposits (10,000¢).

## Stack
| Layer | Technology |
|---|---|
| UI | NiceGUI 3.6.1 (Quasar components, Vue.js underlay) |
| Auth | Google Workspace OAuth 2.0 (`utils/auth.py`) with domain-restricted hd validation |
| Data | Yahoo Finance via `yfinance` (`utils/market.py`) |
| News | Finnhub (`finnhub-python`) — company news in Research tab |
| Storage | Google Cloud Storage via `google-cloud-storage` (`utils/storage.py`) with HMAC-SHA-256 blob keys |
| Sessions | In-memory `_session_store` dict + opaque `secrets.token_urlsafe(32)` tokens |
| Charts | Plotly (pie charts), Lightweight Charts (price history) |
| Deploy | Docker → GCP Cloud Run (us-east1) |

## File Layout
```
├── main.py                  # App entry — routes, UI, all 7 sections, teacher admin, session store
├── requirements.txt         # Production dependencies (no pytest)
├── requirements-dev.txt     # Dev dependencies (pytest, etc.)
├── Dockerfile               # Cloud Run container + pip-audit scan
├── .dockerignore            # Excludes .git, venv, *.json, .env.yaml from Docker image
├── .gitignore               # .env.yaml, .pytest_cache, etc.
├── .env.yaml                # Secret env-var template (gitignored values)
├── ARCHITECTURE.md          # This file
├── security_threat_model.md # STRIDE threat model
├── utils/
│   ├── auth.py              # OAuth URL generation, token exchange, hd validation, teacher check
│   ├── storage.py           # GCS CRUD + GCS token cache (thread-safe) + HMAC key derivation
│   └── market.py            # yfinance wrappers: prices, history, dividends, top movers + global TTL caches
├── services/
│   └── profile.py           # Portfolio computation, alert checks, alert management
└── tests/
    ├── test_audit.py        # Audit log format tests (4)
    ├── test_trading.py      # Trade validation + execution tests (17)
    └── test_security.py     # Negative security tests (25)
```

## Data Flow
```
Browser ←→ NiceGUI server ←→ Google OAuth (login) — hd domain validation
                            ←→ Yahoo Finance (prices, history, movers, macro indicators)
                            ←→ Finnhub (stock news)
                            ←→ Google Cloud Storage (profiles, standings) — HMAC-derived blob keys
```

## Auth Flow
1. `/` detects unauthenticated session → generates OAuth URL with state + code_verifier
2. User redirected to Google OAuth consent screen
3. Google redirects to `/callback?code=...&state=...`
4. `callback_route()` validates state match, enforces rate limit (5 req/min/IP)
5. `exchange_code()` trades code for tokens, fetches user info, validates `hd` against `GOOGLE_HD`
6. Opaque `secrets.token_urlsafe(32)` created; session data stored in `_session_store[token]`
7. Only the token survives in `app.storage.user` (on-disk JSON); all other session fields stripped
8. `is_teacher(email)` checks if email matches a comma-separated list in `TEACHER_EMAILS`

## Session Store
- **In-memory dict** `_session_store: dict[str, dict]` — keyed by opaque token, process-local
- **Token only on disk** — `app.storage.user["_token"]` is the sole session artifact written to NiceGUI's encrypted JSON storage
- **`_session_lock`** — `threading.Lock()` protects all reads/writes to `_session_store`
- **Helper functions:**
  - `_get_session(key, default)` — reads a field from the current token's session
  - `_touch_session()` — updates `last_activity` timestamp on user action (trade, alert, periodic tick)
  - `_clear_session()` — removes token entry from `_session_store`
- **Session timeout** — `_check_session_timeout()` runs on page load; clears session if `last_activity` > 30 min
- **Ephemeral** — lost on instance recycle (no `min-instances`), forces re-auth on cold start

## Persistence
- Each student has a **profile dict** in GCS at `students/{hmac_key(email)}.json`
- Blob keys derived via HMAC-SHA-256 (`_safe_email_key()`) — prevents directory traversal, masks PII
- GCS token cache protected by `_token_lock` to prevent TOCTOU race conditions
- Fields: `name`, `cash`, `holdings`, `history`, `alerts`, `unsettled_cash`, `dividend_tracker`, etc.
- All monetary values stored as **integer cents** — converted at read boundary via `_portfolio()` `/ 100.0`
- Holding price lookups in `_portfolio()` reuse `p["prices"]` from `_portfolio()` — avoiding 2N sequential yfinance calls (main-thread rendering bottleneck)
- Standings/admin loaders batch all unique tickers across students and fetch prices in parallel, then use a `price_map` dict for O(1) lookups
- `load_student_profile(email)` → dict (cached in `_profiles` dict, auto-migrated via `_migrate_profile()`)
- `save_student_profile(email, dict)` → writes to GCS + updates cache
- `get_gcs_database()` → all student profiles (for standings/admin)
- `delete_student_profile(email)` → removes a student profile from GCS (teacher admin)

## CSS Design System
- **Inter font** via Google Fonts `@import` (body only — never `*` selector, which breaks Quasar components)
- **Material Icons** font via `<link>` in `<head>` (required by Quasar for tab indicators / dropdown arrows)
- **CSS variables** in `:root` for colors (`--primary`, `--positive`, `--negative`, etc.), spacing, shadows
- **Custom component classes**: `.topbar`, `.psummary`, `.metric-box`, `.card`, `.chart-container`, `.trade-ticket`, `.market-movers`, `.research-vol`, `.research-chart`, `.page-container`
- **Responsive breakpoint**: `@media (max-width: 640px)` for mobile padding
- **No Tailwind** — all styling via custom CSS classes

## Key Design Decisions
- **No AI features**, no student-facing reset
- **Light theme only**, card-based layout, emoji over icon library
- **`ui.add_css(shared=True)`** at module level — CSS injected once, not per-request
- **`ui.add_head_html(shared=True)`** at module level for CDN scripts — never inside page functions (would accumulate duplicate `<script>` tags on every page load, breaking Vue/Quasar boot)
- **Mutable dict pattern** replaces `nonlocal` in closures (avoids name-resolution issues in some Python 3.9 runtimes)
- **Standings tab and Teacher Admin are teacher-only** via `if is_teacher(email):` guards at tab creation, panel content, and lazy-loader timer
- **All timers created at main-page level** (not inside refreshable functions or tab panels) to prevent "parent slot deleted" RuntimeError
- **yfinance timeouts** set to 3-15s across all calls; errors silently caught
- **All monetary values stored as integer cents** — `_cents()` converts float→int, `_fmt()` formats cents→`$X.XX` string. `_migrate_profile()` converts old float-dollar profiles on first load.
- **In-memory session store** instead of on-disk session files — avoids modifying NiceGUI internal storage, survives across requests with Cloud Run session affinity
- **HMAC key derivation falls back to SHA-256** when `BLOB_KEY_SECRET` is unset — existing GCS blobs remain readable; one-way migration script not required immediately
- **Negative security tests** (25 tests in `tests/test_security.py`) cover rate limit, session integrity, balance invariant, OAuth state mismatch, teacher access control, and HMAC key store

## Performance & Download Bottleneck Fixes
- **Lazy-load pattern**: expensive yfinance calls fire via `async` `ui.timer(once=True)` callbacks that use `asyncio.run_in_executor(ThreadPoolExecutor)` to avoid blocking the event loop
- **Initial page load returns in < 1s** (shell HTML + "Loading..." placeholders)
- **Data populates 0.1s later** when background timers fire
- **Server stays responsive** during yfinance fetches (thread-pool offload)
- **Pie chart price reuse**: Pie charts use `p["prices"]` from `_portfolio()` instead of calling `fetch_stock_market_data()` for each holding — eliminating 2N main-thread yfinance calls per render
- **Mover pre-warm alignment**: `_prewarm_movers()` uses the same ticker batching (stock_groups + ETFs) as `_load_movers()` so cache keys align — no duplicate downloads
- **Cache warmup offloaded**: `warm_price_cache` runs via `.submit(warm_price_cache, ...)` on the global executor instead of blocking page render
- **Global executor**: `_executor = ThreadPoolExecutor(max_workers=4)` replaces ad-hoc fire-and-forget executors, reducing thread creation churn
- **TTLCache** on all yfinance calls: 600s for prices (maxsize 2048), 600s for history, 1800s for movers (maxsize 128), 86400s for dividends

## Tabs
| Tab | Content |
|---|---|
| _(inline)_ | **Macro Indicators** — VIX, CPI (YoY), PPI (YoY), PCE (YoY), DXY — always visible above tabs |
| Portfolio | Allocation pie chart, holdings pie chart, positions table, trade history |
| Trade | Stock selector, live price, buy/sell radio, shares/amount input, review order, market movers. **Sell mode** filters dropdown to owned stocks, shows position info (`📦 Your position: N shares @ $AVG = $VALUE`), and real-time over-limit warnings (`⚠` in red) for insufficient cash (Buy) or exceeding owned shares/value (Sell) |
| Research | Volatility calculator (std%, range, risk level), Price history (Lightweight Charts v5.2), Finnhub news |
| Alerts | Add/delete price alerts (above/below target) |
| Standings | All students sorted by net worth (teacher only) |
| Teacher Admin | Class Portfolio Data table with Remove Student button + Sandbox JSON viewer (teacher only) |

## Market Data (utils/market.py)
- **`fetch_stock_market_data(ticker)`** — live price + company name (cached 600s, maxsize 2048)
- **`fetch_full_history(ticker, period)`** — OHLCV history via yfinance (cached 600s)
- **`get_top_movers(tickers)`** — top gainers/losers by % change (cached 1800s, maxsize 128)
- **`get_dividends(ticker)`** — dividend history (cached 86400s)
- **`warm_price_cache(tickers)`** — preloads prices via global `ThreadPoolExecutor(max_workers=4)`

All calls wrapped with `TTLCache`; errors caught and silently handled.

## Macro Indicators
| Indicator | Ticker | Source | Calculation |
|---|---|---|---|
| VIX | `^VIX` | yfinance | Raw index value; green <15, yellow 15-25, red >25 |
| CPI | `CPIAUCNS` | FRED CSV (free) | YoY % via `(latest / 12mo_ago - 1) * 100` |
| PPI | `PPIACO` | FRED CSV (free) | YoY % via `(latest / 12mo_ago - 1) * 100` |
| PCE | `PCEPI` | FRED CSV (free) | YoY % via `(latest / 12mo_ago - 1) * 100` |
| DXY | `DX-Y.NYB` | yfinance | Raw index + 1-month % change |

FRED data fetched via `fred.stlouisfed.org/graph/fredgraph.csv?id={series}` — no API key required. All 5 macro sources are fetched concurrently via `ThreadPoolExecutor(max_workers=5)`. Results are cached in `_MACRO_CACHE` (module-level dict, 290s TTL) so redundant fetches across users are eliminated. Async on page load, refreshes every 5 minutes.

## Finnhub News
- Lazy client init (`_fh()`) reads `FINNHUB_API_KEY` from env
- `company_news(symbol, _from, to)` returns top 5 articles (Yahoo-sourced filtered out)
- Displayed in Research tab below chart, updates on ticker selection
- Free tier: 60 calls/minute

## Timer Architecture
All timers are created at the `main_page()` top level (outside refreshable functions and tab panels) to ensure stable parent slots:

| Timer | Interval | Purpose |
|---|---|---|
| `_load_summary` | 0.1s (once) | Fetches portfolio data for summary bar |
| `_macro_worker` | 0.1s (once) + 300s (repeating) | Fetches VIX, CPI, PPI, PCE, DXY values |
| `_load_portfolio` | 0.1s (once) | Fetches portfolio data for Portfolio tab |
| `_load_movers` | 0.1s (once) | Fetches top gainers/losers for Market Movers (100-ticker batches) |
| `_load_standings` | 0.1s (once) | Loads all profiles for Standings table (teacher only) |
| `_load_admin` | 0.1s (once) | Loads all profiles for Teacher Admin table (teacher only) |
| `_tick` | 300s (repeating) | Re-fetches data and refreshes all refreshable sections |

All blocking callbacks are `async` functions that delegate yfinance calls to `asyncio.run_in_executor` (thread pool) to keep the event loop free. Internal parallelism:

- `_fetch_macro()` uses `ThreadPoolExecutor(max_workers=5)` to fetch VIX, 3 FRED series, and DXY concurrently instead of sequentially. Results cached globally (`_MACRO_CACHE`, 290s TTL).
- `_load_standings()` and `_load_admin()` batch all unique tickers across all student profiles, fetch prices in parallel, then use a `price_map` dict for O(1) lookups — eliminating N×M sequential yfinance calls.

## Refreshable Sections
- `summary()` — top bar with cash balance, invested, unsettled, dividends, total
- `macro_bar()` — inline macro indicators (VIX, CPI, PPI, PCE, DXY)
- `portfolio_content()` — allocation charts, positions table, trade history
- `standings_content()` — sorted standings table (teacher only)
- `admin_table()` — class portfolio data table with Remove Student button (teacher only)
- `movers()` — market movers gainers/losers lists (inside Trade tab)
- `confirm_card()` — trade confirmation card (inside Trade tab)
- `alert_list()` — alert list (inside Alerts tab)

## Chart Initialization (Lightweight Charts v5.2)
- CDN script loaded at module level via `ui.add_head_html(shared=True)` — never inside page functions
- v5 API uses `c.addSeries(LightweightCharts.CandlestickSeries, opts)` instead of `c.addCandlestickSeries(opts)`
- Series types passed as constructor references (`LightweightCharts.LineSeries`, `LightweightCharts.CandlestickSeries`) — not string literals
- `ResizeObserver` on `#tvchart` element replaces polling for reliable resize when tab becomes visible
- Chart JS retries via `setTimeout(initTv, 100)` until `LightweightCharts` global and `#tvchart` element exist (up to 10s via `_tvt` timestamp guard)
- All `window.__tv.*` calls guarded with `if (window.__tv) return` / `if (!window.__tv)` null-checks
- `ui.run_javascript` wrapped in try/catch with `console.error` fallback

## Local Dev
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install urllib3==1.26.20
python main.py  # → http://localhost:8080
```

Note: `ui.run()` uses `reload=False` to avoid watchfiles interference during active development.

OAuth requires both `client_secret.json` and `math-finance-simulator-51d674093aa1.json` in the project root (gitignored).
Set `REDIRECT_URI=http://localhost:8080/callback` env var for local OAuth to work.

## Running Tests
```bash
TEACHER_EMAILS="rpiana@stjohnsguam.com" GOOGLE_HD="stjohnsguam.com" \
  BLOB_KEY_SECRET="test-secret" python3 -m pytest tests/ -v
```

Requires `requirements-dev.txt` for `pytest`.

## Deployment

### Manual
```bash
# Build container image
gcloud builds submit --tag gcr.io/math-finance-simulator/app

# Deploy
gcloud run deploy math-finance-simulator \
  --image gcr.io/math-finance-simulator/app \
  --region us-east1 --allow-unauthenticated \
  --memory 512Mi --timeout 600 --session-affinity \
  --update-env-vars FINNHUB_API_KEY=your_key_here,GOOGLE_HD=your.school.edu,BLOB_KEY_SECRET=your_secret_here,REDIRECT_URI=https://your-service-xxxxxxxxxx-ue.a.run.app/callback
```

### Auto-deploy (Cloud Build Trigger)
A `cloudbuild.yaml` is included in the repo. To enable auto-deploy on `git push` to `main`:

1. Go to [Cloud Build Triggers](https://console.cloud.google.com/cloud-build/triggers?project=math-finance-simulator)
2. Click "Connect Repository" → "GitHub"
3. Install the Google Cloud Build GitHub App for `rpiana133/math_finance_simulator`
4. Select the repo, create a push trigger:
   - **Name**: `deploy-to-cloud-run`
   - **Event**: Push to branch — `^main$`
   - **Config**: `cloudbuild.yaml` (repo root)
5. The trigger preserves existing Cloud Run env vars (no `--update-env-vars` in the build config — env vars set via Cloud Console or initial manual deploy are retained).
```

Required environment variables:
| Variable | Source | Purpose |
|----------|--------|---------|
| `STORAGE_SECRET` | Secret Manager | Encryption key for profile data |
| `GOOGLE_CLIENT_SECRET` | Secret Manager | Full OAuth client JSON |
| `GCS_SERVICE_ACCOUNT` | Secret Manager | Full GCS service account JSON |
| `BLOB_KEY_SECRET` | Secret Manager | HMAC key for GCS blob path derivation |
| `FINNHUB_API_KEY` | Plain env | Finnhub API key (for news section) |
| `TEACHER_EMAILS` | Plain env | Comma-separated teacher emails for admin access |
| `GOOGLE_HD` | Plain env | Google Workspace domain to restrict logins |
| `REDIRECT_URI` | Plain env | (Optional) overrides auto-detected OAuth callback URL |

OAuth redirect URIs must include both `http://localhost:8080/callback` and `https://*.run.app/callback` in Google Cloud Console.

Note: `.dockerignore` excludes `*.json` and `.env.yaml` from the Docker image — secrets are injected at runtime via env vars.

## Periodic Processes
- **Every 5 min**: refresh summary, portfolio, standings, admin, macro indicators (via 300s async tick timer with thread-pool offload)
- **On page load**: settlement (24h T+1), weekly deposit ($100/7d = 10,000¢), dividend collection, alert checks, movers cache pre-fill
