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
│   ├── auth.py              # OAuth URL generation, token exchange (returns user_info + credentials_dict), hd validation, teacher check
│   ├── storage.py           # GCS CRUD + GCS token cache (thread-safe) + HMAC key derivation
│   └── market.py            # yfinance wrappers: prices, history, dividends, top movers + global TTL caches
├── services/
│   ├── profile.py           # Portfolio computation, dust-holding cleanup, alert checks, shared ThreadPoolExecutor(8)
│   └── sheets.py            # Google Sheets weekly tracker: graph-friendly row-per-holding snapshots, ISO-week dedup/rewrite, legacy reset, formatting
└── tests/
    ├── test_audit.py        # Audit log format tests (4)
    ├── test_trading.py      # Trade validation + execution tests (19)
    └── test_security.py     # Negative security tests (27)
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
5. `exchange_code()` trades code for tokens, fetches user info, validates `hd` against `GOOGLE_HD`; returns `(user_info, credentials_dict)` tuple — credentials_dict includes the OAuth token set serialized as JSON (token, refresh_token, token_uri, client_id, client_secret, scopes), used to call the Sheets API on the student's own behalf
6. Opaque `secrets.token_urlsafe(32)` created; session data stored in `_session_store[token]`, including `oauth_creds` (the JSON-serializable credentials dict)
7. Only the token survives in `app.storage.user` (on-disk JSON); all other session fields stripped
8. `is_teacher(email)` checks if email matches a comma-separated list in `TEACHER_EMAILS`
9. **Curfew gate** — if `_in_curfew()` is true (9pm–8am Guam) and the user is not a teacher, the login is rejected. Logged-out visitors see a "class closed" front page; authenticated students are signed out

OAuth scopes granted (on consent screen):
- `classroom.coursework.students` — read/write classroom coursework
- `userinfo.email` / `userinfo.profile` — identify the logged-in student
- `spreadsheets` — create/update the student's own "My Stock Tracker" sheet
- `openid` — OpenID Connect

## Session Store
- **In-memory dict** `_session_store: dict[str, dict]` — keyed by opaque token, process-local
- **Token only on disk** — `app.storage.user["_token"]` is the sole session artifact written to NiceGUI's encrypted JSON storage
- **`_session_lock`** — `threading.Lock()` protects all reads/writes to `_session_store`
- **Helper functions:**
  - `_get_session(key, default)` — reads a field from the current token's session
  - `_touch_session()` — updates `last_activity` timestamp on timer pings (heartbeat, tick)
  - `_touch_client_activity()` — updates `last_client_activity` timestamp from real user activity (via `/_activity`)
  - `_clear_session()` — removes token entry from `_session_store`
- **Session timeout** — `_check_session_timeout()` runs on page load; clears session if `last_activity` > 30 min
- **Idle disconnect** — `_check_idle_timeout()` (30s timer) clears session if `last_client_activity` is > 15 min old; students only (teachers exempt). Decoupled from timer pings so a background tab isn't mistaken for real activity
- **Curfew kick** — `_check_curfew_kick()` (60s timer) signs out students when curfew starts (9pm Guam); teachers exempt
- **Ephemeral** — lost on instance recycle (no `min-instances`), forces re-auth on cold start

## Persistence
- Each student has a **profile dict** in GCS at `students/{hmac_key(email)}.json`
- Blob keys derived via HMAC-SHA-256 (`_safe_email_key()`) — prevents directory traversal, masks PII
- GCS token cache protected by `_token_lock` to prevent TOCTOU race conditions
- Fields: `name`, `cash`, `holdings`, `history`, `alerts`, `unsettled_cash`, `unsettled_entries`, `dividend_tracker`, etc.
- All monetary values stored as **integer cents** — converted at read boundary via `_portfolio()` `/ 100.0`
- Holding price lookups in `_portfolio()` reuse `p["prices"]` from `_portfolio()` — avoiding 2N sequential yfinance calls (main-thread rendering bottleneck)
- Standings/admin loaders batch all unique tickers across students and fetch prices in parallel, then use a `price_map` dict for O(1) lookups
- `load_student_profile(email)` → dict (cached in `_profiles` dict, auto-migrated via `_migrate_profile()`)
- `_clean_dust_holdings(profile)` → drops zero-cost/zero-share holdings on load (self-heal for fractional-sell dust) — also applied in all 4 standings/admin loaders
- `save_student_profile(email, dict)` → writes to GCS + updates cache
- `get_gcs_database()` → all student profiles (for standings/admin) — cached for 60s
- `delete_student_profile(email)` → removes a student profile from GCS (teacher admin)
- `delete_student_profile_by_key(gcs_key)` → removes by hash key (for unknown-email profiles)
- **Unsettled cash flow**: sell proceeds go to `unsettled_cash` (not `cash`); settles to `cash` after 24h via `_process_settlement()`

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
- **yfinance timeouts** set to 3-5s across all calls; errors silently caught
- **All monetary values stored as integer cents** — `_cents()` converts float→int, `_fmt()` formats cents→`$X.XX` string. `_migrate_profile()` converts old float-dollar profiles on first load.
- **In-memory session store** instead of on-disk session files — avoids modifying NiceGUI internal storage, survives across requests with Cloud Run session affinity
- **HMAC key derivation falls back to SHA-256** when `BLOB_KEY_SECRET` is unset — existing GCS blobs remain readable; one-way migration script not required immediately
- **Negative security tests** (27 tests in `tests/test_security.py`) cover rate limit, session integrity, balance invariant, OAuth state mismatch, teacher access control, and HMAC key store
- **Token bucket rate limiter** (`_TokenBucket` in `utils/market.py`) — max 15 concurrent yfinance calls with 8 tokens/sec refill (relaxed from 5/2 for 18 concurrent users); all acquires use `timeout=3` to fail fast instead of hanging
- **Dust-holding defense**: fractional-share sells can leave a residual position with `total_cost == 0` but `shares > 0`, which would crash `_portfolio()` with `ZeroDivisionError`. Guards skip zero-cost/zero-share positions, sell-deletion tolerates `< 1e-6` share residue, and `_clean_dust_holdings()` self-heals profiles on load and in admin/standings loaders

## Performance & Download Bottleneck Fixes
- **Lazy-load pattern**: expensive yfinance calls fire via `async` `ui.timer(once=True)` callbacks that use `asyncio.run_in_executor(ThreadPoolExecutor)` to avoid blocking the event loop
- **Initial page load returns in < 1s** (shell HTML + "Loading..." placeholders)
- **Data populates 0.1s later** when background timers fire
- **Server stays responsive** during yfinance fetches (thread-pool offload)
- **Pie chart price reuse**: Pie charts use `p["prices"]` from `_portfolio()` instead of calling `fetch_stock_market_data()` for each holding — eliminating 2N main-thread yfinance calls per render
- **Mover pre-warm alignment**: `_prewarm_movers()` uses the same ticker batching (stock_groups + ETFs) as `_load_movers()` so cache keys align — no duplicate downloads
- **Mover state machine**: `movers_load_action(cache, now, ttl)` classifies the shared cache as `refresh` / `wait` / `fetch`. `_load_movers` is the sole owner of the `loading` flag: when another worker holds it, the page waits (bounded 20s) then refreshes instead of dead-ending. This prevents the login pre-warm from permanently wedging the module-global cache
- **Cache warmup offloaded**: `warm_price_cache` runs via `.submit(warm_price_cache, ...)` on the global executor instead of blocking page render
- **Global executor**: `_executor = ThreadPoolExecutor(max_workers=16)` — increased from 4 to handle18 simultaneous users
- **Shared portfolio executor**: `_shared_executor = ThreadPoolExecutor(max_workers=8)` in `services/profile.py` — replaces per-call ThreadPoolExecutor creation
- **TTLCache** on all yfinance calls: 600s for prices (maxsize 2048), 600s for history, 1800s for movers (maxsize 128), 86400s for dividends
- **Token bucket rate limiter**: `_yf_limiter` with capacity=15, rate=8.0 — prevents yfinance rate-limit hangs; double-cache-check pattern avoids redundant fetches; all acquires `timeout=3`
- **Bounded portfolio fetch**: `_portfolio()` waits on `as_completed(futs, timeout=15)` — a stale holding's ticker is skipped rather than blocking the whole render
- **Bounded price/dividend fetches**: `_price_executor` (8 workers) wraps `fast_info` and dividend lookups with a 5s timeout so a hung yfinance thread can't strand a worker
- **Bounded history fallback**: `yf.download` period fallback loop uses 5s timeout per period (down from 15s)
- **Login warm dedupe**: `warm_price_cache` submitted at most once per 60s (`_warm_lock` + `_warm_state`) — an 18-student login stampede submits a single warm batch instead of 18 redundant ones
- **GCS database cached**: `get_gcs_database()` uses 60s TTL cache — reduces GCS API calls from admin/standings refreshes
- **GCS HTTP timeouts reduced**: all 5 GCS HTTP calls use `timeout=5` (down from 10s) — prevents cascade hangs when GCS is slow
- **Shared movers cache**: global `_movers_cache` with 5-min TTL + atomic loading lock — prevents cross-user duplicate fetches. The login pre-warm only warms the yfinance TTL cache and never touches `_movers_cache`; `_load_movers` alone sets `loading`/`loaded`/`ts`
- **Ticker search hang fix**: merged `_upd_sel` + `_upd_preview` into single `_on_sel_change` handler; `_upd_preview` reads price from `_sel_price_state` cache instead of re-fetching
- **Unsettled cash in net worth**: standings and admin `nw = ((cash + unsettled) / 100) + mv` — previously excluded unsettled, causing phantom losses after sells
- **Fireproof `_tick()`**: try/finally ensures `_touch_session()` always fires — prevents 30-min session timeout if `_portfolio()` throws
- **Separate heartbeat timer**: 60s timer calls `_touch_session()` independently of `_tick()` — prevents idle-browsing session expiry
- **Curfew block**: app is server-side locked from 9pm–8am Guam (`_CURFEW_CLOSE_UTC_HOUR=11`, `_CURFEW_OPEN_UTC_HOUR=22`; Guam is UTC+10 with no DST so a fixed UTC window holds year-round). Teachers exempt. Server-side enforcement means the block can't be bypassed by editing client JS
- **Weekend/holiday market close**: on Saturdays, Sundays, and US stock-market holidays (observed on the Guam calendar date via `_is_market_closed()` + `_US_MARKET_HOLIDAYS_2026`), students can still log in and **view** their portfolio but **cannot trade** — `_execute_trade()` rejects orders and a 🔒 banner explains why. Unlike the curfew (full app block), this allows read-only access. Holiday dates are matched against `_guam_date()`
- **15-min idle disconnect**: real user activity (mousemove/keydown/click/touch/wheel) is echoed to `/_activity`; the 30s `_check_idle_timeout` timer signs out students idle > 15 min. Distinct `last_client_activity` field keeps the idle check independent of `_heartbeat`/`_tick` pings, so an open background tab counts as idle
- **Cost motivation**: curfew + idle disconnect drive idle Cloud Run instances to 0 outside class hours, cutting idle billable instance time and monthly spend (the app had instances alive all night from students' open tabs)
- **Artifact Registry cleanup policy**: the `cloud-run-source-deploy` repository keeps only the 3 newest image digests per deploy (cleanup policy `keep-latest-3`), purging the orphaned untagged images that had been accumulating storage cost each deploy
- **Async page load**: `_get(email)` wrapped in `run_in_executor` — `main_page()` is `async def`, no longer blocks event loop
- **yfinance thread-safety**: yfinance is not thread-safe — previously, concurrent `yf.Ticker(...).fast_info` / `yf.download` calls from the shared executors cross-contaminated, with many different tickers returning the same wrong price and inflating net worth. All yfinance reads (`fetch_stock_market_data`, `fetch_full_history`, `get_dividends`, `warm_price_cache`, `get_top_movers`) are now serialized behind a module-level reentrant lock (`_yf_lock`), so each ticker gets its own correct price even under concurrency

## Tabs
| Tab | Content |
|---|---|
| _(inline)_ | **Macro Indicators** — VIX, CPI (YoY), PPI (YoY), PCE (YoY), DXY — always visible above tabs |
| Portfolio | Allocation pie chart, holdings pie chart, positions table, trade history |
| Trade | Stock selector, live price, buy/sell radio, shares/amount input, review order, market movers. **Sell mode** filters dropdown to owned stocks, shows position info (`📦 Your position: N shares @ $AVG = $VALUE`), and real-time over-limit warnings (`⚠` in red) for insufficient cash (Buy) or exceeding owned shares/value (Sell). A sell that leaves `< 1e-6` shares or a $0 cost basis deletes the holding entirely (prevents float-dust positions) |
| Research | Volatility calculator (std%, range, risk level), Price history (Lightweight Charts v5.2), Finnhub news |
| Alerts | Add/delete price alerts (above/below target) |
| Standings | All students sorted by net worth (teacher only) |
| Teacher Admin | Class Portfolio Data table with Remove Student button + Sandbox JSON viewer (teacher only) |

## Market Data (utils/market.py)
- **`fetch_stock_market_data(ticker)`** — live price + company name (cached 600s, maxsize 2048) — rate-limited via `_yf_limiter`
- **`fetch_full_history(ticker, period)`** — OHLCV history via yfinance (cached 600s) — rate-limited
- **`get_top_movers(tickers)`** — top gainers/losers by % change (cached 1800s, maxsize 128) — rate-limited
- **`get_dividends(ticker)`** — dividend history (cached 86400s) — rate-limited
- **`warm_price_cache(tickers)`** — preloads prices via shared `_shared_executor` in `services/profile.py`
- **`_TokenBucket`** — token-bucket rate limiter (capacity=15, rate=8.0) prevents yfinance rate-limit hangs
- **`POPULAR_STOCKS`** includes Samsung (`SSNLF`) and SK Hynix (`SKHY`) among 80+ stocks
- **`POPULAR_ETFS`** includes 50+ ETFs — Schwab, Vanguard, iShares, Invesco, Direxion, ProShares, Xtrackers

All calls wrapped with `TTLCache` and `_yf_limiter.acquire()` — errors caught and silently handled.

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

## Google Sheets Weekly Tracker
Students can save a weekly snapshot of their portfolio to a personal Google Sheet via the **"Save to Google Sheets"** button in the top bar.

### How it works
1. On first export, a **"My Stock Tracker" spreadsheet** is created in the student's Google Drive (via `spreadsheets.create`), and the spreadsheet ID is persisted in `profile["spreadsheet_id"]` in their GCS profile
2. The student's own OAuth token (`_session_store[token]["oauth_creds"]`) carries the `spreadsheets` scope; Sheets API calls run on behalf of the student using their own credentials (not a service account)
3. On click, `save_weekly_snapshot(oauth_creds, portfolio, spreadsheet_id)` runs in the executor thread pool:
   - Writes **one row per holding** for the current ISO week (e.g. `2026-W36`), repeating `Net Worth` on each row so a whole-account value-over-time chart is easy too
   - `_weeks_map()` scans column A for an existing week key; same week rows are **deleted** (via `batchUpdate.deleteDimension`) then rewritten; new weeks **append** after the last data row
   - Legacy blob-format sheets (old 9-col schema with a merged `Cash` cell) are auto-detected by `_is_legacy()` and **reset** to the new schema
   - Formatting applied via `spreadsheets().batchUpdate`: bold + filled header row, frozen header row, column widths, and numeric cell formatting
4. The spreadsheet ID is saved to the profile on first creation; subsequent exports reuse it (avoids Drive API scope entirely — only `spreadsheets` scope is needed)

### Sheet columns
| A | B | C | D | E | F | G | H | I |
|---|---|---|---|---|---|---|---|---|
| Week | Date | Ticker | Shares | Avg Price | Live Price | Value | Return % | Net Worth |

All price/share/return/net-worth columns are stored as plain numbers (no `$` prefix) so sheets can chart Live Price, Value, or Net Worth against Week/Date without string parsing.

### Key design decisions
- **No Drive API scope** — `drive.files().list()` is not used; the spreadsheet ID is stored in the student's GCS profile instead, avoiding the need to add a Drive scope to the OAuth consent screen
- **Manual trigger only** — no automatic weekly cron; students click the button when they want a snapshot
- **Per-student sheet** — each student owns one sheet; the app creates it on first use and never needs to find it again
- **In-memory session store for tokens** — `oauth_creds` lives in `_session_store` (not on disk); survives requests via session affinity but is lost on instance recycle (same ephemeral behavior as other session fields)
- **Scope bootstrapping**: existing students who logged in before the `spreadsheets` scope was added must re-login to pick it up. If the `spreadsheets` scope is missing from their token, the Sheets button shows a prompt to re-sign in

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
| `_tick` | 300s (repeating) | Re-fetches data and refreshes all refreshable sections; wrapped in try/finally to always touch session |
| `_heartbeat` | 60s (repeating) | Calls `_touch_session()` independently — prevents idle-browsing session timeout |
| `_check_session_timeout` | 60s (repeating) | Clears session + redirects to `/` if `last_activity` > 30 min |
| `_check_idle_timeout` | 30s (repeating) | Clears session + redirects to `/` if `last_client_activity` > 15 min (real user activity only; teachers exempt) |
| `_check_curfew_kick` | 60s (repeating) | Clears session + redirects to `/` when curfew starts (9pm Guam); teachers exempt |

- **All blocking callbacks are `async` functions** that delegate yfinance calls to `asyncio.run_in_executor` (thread pool) to keep the event loop free. `_load_summary` and `_load_portfolio` wrap the executor call in try/except so a profile anomaly degrades to empty data instead of leaving the tab spinning
- **Client activity ping**: injected JS listens for `mousemove`/`keydown`/`click`/`touchstart`/`wheel` and POSTs the session token to `/_activity` (throttled, tracker waits after each ping). This populates `last_client_activity`, which drives `_check_idle_timeout` — independent of server timer pings

Internal parallelism:

- `_fetch_macro()` uses `ThreadPoolExecutor(max_workers=5)` to fetch VIX, 3 FRED series, and DXY concurrently instead of sequentially. Results cached globally (`_MACRO_CACHE`, 290s TTL).
- `_load_standings()` and `_load_admin()` batch all unique tickers across all student profiles, fetch prices in parallel, then use a `price_map` dict for O(1) lookups — eliminating N×M sequential yfinance calls.
- `_portfolio()` (in `services/profile.py`) submits holding price fetches to `_shared_executor` and waits via `as_completed(..., timeout=15)` — slow/stale tickers are skipped so a single laggard can't block the render.
- `_price_executor` (8 workers in `utils/market.py`) bounds `fast_info` and dividend fetches with a 5s timeout so they never hang a worker thread.
- Login-time `warm_price_cache` is deduplicated via `_warm_lock` + `_warm_state` (60s TTL) — only the first login per 60s submits warm tasks.

## Refreshable Sections
- `summary()` — top bar with cash balance, invested, unsettled, dividends, total
- `macro_bar()` — inline macro indicators (VIX, CPI, PPI, PCE, DXY)
- `portfolio_content()` — allocation charts, positions table, trade history
- `standings_content()` — sorted standings table (teacher only)
- `admin_table()` — class portfolio data table with Remove Student button (teacher only); clicking a row opens holdings dialog with trade history
- `movers()` — market movers gainers/losers lists (inside Trade tab)
- `confirm_card()` — trade confirmation card (inside Trade tab)
- `alert_list()` — alert list (inside Alerts tab)
- `_sheet_status()` — Google Sheets export button + spinner + status message (top bar, below summary)

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
