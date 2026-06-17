# Math Finance Simulator — Architecture

## Overview
A classroom stock market simulation built with NiceGUI, Google OAuth, Yahoo Finance data, and Google Cloud Storage persistence. Students trade fictional portfolios with $1k starting cash (100,000¢) and $100/week deposits (10,000¢).

## Stack
| Layer | Technology |
|---|---|
| UI | NiceGUI 3.6.1 (Quasar components, Vue.js underlay) |
| Auth | Google Workspace OAuth 2.0 (`utils/auth.py`) |
| Data | Yahoo Finance via `yfinance` (`utils/market.py`) |
| News | Finnhub (`finnhub-python`) — company news in Research tab |
| Storage | Google Cloud Storage via `google-cloud-storage` (`utils/storage.py`) |
| Charts | Plotly (pie charts), Lightweight Charts (price history) |
| Deploy | Docker → GCP Cloud Run (us-east1) |

## File Layout
```
├── main.py                  # App entry — routes, UI, all 7 sections, teacher admin
├── requirements.txt         # Dependencies
├── Dockerfile               # Cloud Run container
├── .dockerignore            # Excludes .git, venv, *.json, .env.yaml from Docker image
├── .env.yaml                # Secret env-var template (gitignored values)
├── ARCHITECTURE.md          # This file
├── utils/
│   ├── auth.py              # OAuth URL generation, token exchange, teacher check
│   ├── storage.py           # GCS CRUD: load/save/delete profiles, get full database
│   └── market.py            # yfinance wrappers: prices, history, dividends, top movers
└── client_secret.json       # Google OAuth credentials (gitignored)
```

## Data Flow
```
Browser ←→ NiceGUI server ←→ Google OAuth (login)
                           ←→ Yahoo Finance (prices, history, movers, macro indicators)
                           ←→ Finnhub (stock news)
                           ←→ Google Cloud Storage (profiles, standings)
```

## Auth Flow
1. `/login` redirects user to Google OAuth consent screen
2. Google redirects to `/callback?code=...`
3. `exchange_code()` trades code for tokens, fetches user info (name, email)
4. User info stored in `app.storage.user` (NiceGUI encrypted session cookie)
5. `is_teacher(email)` checks if email matches `rpiana@stjohnsguam.com`

## Persistence
- Each student has a **profile dict** in GCS at `students/{email}.json`
- Fields: `name`, `cash`, `holdings`, `history`, `alerts`, `unsettled_cash`, `dividend_tracker`, etc.
- All monetary values stored as **integer cents** — converted at read boundary via `_portfolio()` `/ 100.0`
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

## Performance
- **Lazy-load pattern**: expensive yfinance calls fire via `async` `ui.timer(once=True)` callbacks that use `asyncio.run_in_executor(ThreadPoolExecutor)` to avoid blocking the event loop
- **Initial page load returns in < 1s** (shell HTML + "Loading..." placeholders)
- **Data populates 0.1s later** when background timers fire
- **Server stays responsive** during yfinance fetches (thread-pool offload)
- **Cache warmup** (`warm_price_cache`) preloads user holdings in a background thread at page load
- **Movers cache pre-fill**: `get_top_movers(ALL_TICKERS)` fired on login via background thread so the 30-min cache is ready before the page renders
- **TTLCache** on all yfinance calls: 600s for prices, 600s for history, 1800s for movers, 86400s for dividends

## Tabs
| Tab | Content |
|---|---|
| _(inline)_ | **Macro Indicators** — VIX, CPI (YoY), PPI (YoY), PCE (YoY), DXY — always visible above tabs |
| Portfolio | Allocation pie chart, holdings pie chart, positions table, trade history |
| Trade | Stock selector, live price, buy/sell radio, shares/amount input, review order, market movers |
| Research | Volatility calculator (std%, range, risk level), Price history (Lightweight Charts v5.2), Finnhub news |
| Alerts | Add/delete price alerts (above/below target) |
| Standings | All students sorted by net worth (teacher only) |
| Teacher Admin | Class Portfolio Data table with Remove Student button + Sandbox JSON viewer (teacher only) |

## Market Data (utils/market.py)
- **`fetch_stock_market_data(ticker)`** — live price + company name (cached 600s)
- **`fetch_full_history(ticker, period)`** — OHLCV history via yfinance (cached 600s)
- **`get_top_movers(tickers)`** — top gainers/losers by % change (cached 1800s, pre-filled at login)
- **`get_dividends(ticker)`** — dividend history (cached 86400s)
- **`warm_price_cache(tickers)`** — preloads prices via ThreadPoolExecutor

All calls wrapped with `TTLCache`; errors caught and silently handled.

## Macro Indicators (via yfinance)
| Indicator | Ticker | Calculation |
|---|---|---|
| VIX | `^VIX` | Raw index value; green <15, yellow 15-25, red >25 |
| CPI | `CPIAUCNS` | YoY % via `(latest / 1yr_ago - 1) * 100` |
| PPI | `PPIACO` | YoY % via `(latest / 1yr_ago - 1) * 100` |
| PCE | `PCEPI` | YoY % via `(latest / 1yr_ago - 1) * 100` |
| DXY | `DX-Y.NYB` | Raw index + 1-month % change |

Fetched asynchronously on page load, refreshes every 5 minutes.

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

All blocking callbacks are `async` functions that delegate yfinance calls to `asyncio.run_in_executor` (thread pool) to keep the event loop free.

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
pip install urllib3==1.26.20
python main.py  # → http://localhost:8080
```

Note: `ui.run()` uses `reload=False` to avoid watchfiles interference during active development.

OAuth requires both `client_secret.json` and `math-finance-simulator-51d674093aa1.json` in the project root (gitignored).
Set `REDIRECT_URI=http://localhost:8080/callback` env var for local OAuth to work.

## Deployment
```bash
# Build container image
gcloud builds submit --tag gcr.io/math-finance-simulator/app

# Deploy
gcloud run deploy math-finance-simulator \
  --image gcr.io/math-finance-simulator/app \
  --region us-east1 --allow-unauthenticated \
  --memory 512Mi --timeout 300 \
  --update-env-vars FINNHUB_API_KEY=your_key_here
```

Required environment variables (set via `--env-vars-file` on first deploy, or `--update-env-vars` for single var updates):
- `STORAGE_SECRET` — encryption key for profile data
- `GOOGLE_CLIENT_SECRET` — full OAuth client JSON
- `GCS_SERVICE_ACCOUNT` — full GCS service account JSON
- `FINNHUB_API_KEY` — Finnhub API key (for news section)
- `REDIRECT_URI` — (optional) overrides auto-detected callback URL

OAuth redirect URIs must include both `http://localhost:8080/callback` and `https://*.run.app/callback` in Google Cloud Console.

Note: `.dockerignore` excludes `*.json` and `.env.yaml` from the Docker image — secrets are injected at runtime via env vars.

## Periodic Processes
- **Every 5 min**: refresh summary, portfolio, standings, admin, macro indicators (via 300s async tick timer with thread-pool offload)
- **On page load**: settlement (24h T+1), weekly deposit ($100/7d = 10,000¢), dividend collection, alert checks, movers cache pre-fill
