# Changelog

## 2026-09-04

### Added
- **Market closes on weekends and US stock-market holidays (Guam time)**: the simulator now behaves like a real exchange — students can still log in and view their portfolio/holdings/charts on Saturdays, Sundays, and US market holidays (observed on the Guam calendar date, e.g. Labor Day Mon Sep 7), but **buy/sell orders are rejected** with a clear "Market closed" message. A visible 🔒 banner notifies students why trading is disabled. The existing 9pm–8am curfew is unchanged (separate, stricter whole-app block). Holiday dates live in `_US_MARKET_HOLIDAYS_2026` in `main.py` and should be refreshed annually.
- **Google Sheets tracker reformat — graph-friendly row-per-holding layout**: the sheet no longer crams the whole portfolio into one blob cell. Each snapshot now writes **one row per holding** in a clean schema `Week, Date, Ticker, Shares, Avg Price, Live Price, Value, Return %, Net Worth` (all numeric so Sheets can chart price-over-time directly — students filter by Ticker to plot Live Price vs Week). Re-exporting the same ISO week rewrites that week's rows in place; legacy blob-format sheets are auto-detected and reset. Formatting applied via the API: bold filled header row that's frozen, column widths, and number formats. A no-holdings/all-cash snapshot writes a single Net Worth row so the total still charts.
- **'Weekly Log' price-history tab**: a second tab (`Weekly Log`) now tracks **week-to-week price changes since buy**, not just the single snapshot. Each held stock gets one row per week (`Week, Date, Ticker, Close Price, Avg Price, Value, Return %`) — backfilled from yfinance weekly (Friday) closes from the buy date forward, plus the current week's live price, so students can graph Close Price vs Week for any ticker. The log is rebuilt idempotently on each Save (no duplicate weekly rows); `profile["weekly_log_last_exported"]` records the last exported ISO week.
- **Cloud Run usage tracking script** (`scripts/track_usage.py`): queries Cloud Monitoring for billable instance time and request count over a date range (Guam-local), writes hourly + daily CSVs and a JSON snapshot, and prints a weekday/weekend split plus a request-based cost projection. Grouped to one aggregate series, so repeated-use days don't double-count. Used to track September usage and project the month's Cloud Run cost.

### Fixed
- **yfinance not thread-safe — wrong/inflated prices under concurrency**: the app's parallel price fetches (via the shared `_shared_executor` in `_portfolio`, `_price_executor`, `warm_price_cache`, movers, history, and dividends) cross-contaminated each other because yfinance is not thread-safe — many different tickers all returned the same wrong price (e.g. everything = SKHY's `$163.68`). This inflated student net worth in the Portfolio tab, Standings, and Admin views, producing phantom accounts worth tens of thousands of dollars. All yfinance reads are now serialized behind a module-level reentrant lock (`_yf_lock` in `utils/market.py`), so each ticker gets its own correct price. Verified: 20/20 distinct tickers now return correct distinct prices under a 12-thread concurrency stress test.

### Changed
- **Idle timeout reduced from 15 to 10 minutes**: `_IDLE_TIMEOUT` is now 600s — students with no real activity (mouse/keyboard/touch) for 10 minutes are signed out automatically (teachers exempt), further cutting idle instance time.

## 2026-09-02

### Added
- **Curfew block**: the simulator is unavailable 9pm–8am (Chamorro Time), enforced server-side so it can't be bypassed via client JS. Students get a "market closed" front page with a teacher sign-in path; new student logins are rejected during curfew; already-open student tabs crossing 9pm are signed out. Teachers (`TEACHER_EMAILS`) are exempt.
- **15-minute idle disconnect**: the browser reports real user activity (mousemove/keydown/click/touch/wheel) to a new `/_activity` endpoint; sessions with no real activity for 15 minutes are signed out automatically. Teachers are exempt.
- **Artifact Registry cleanup policy**: `cloud-run-source-deploy` keeps only the 3 newest images per deploy, deleting the ~27 orphaned digests that had been accumulating ~$1/mo in storage.
- **Google Sheets weekly tracker**: "Save to Google Sheets" button in the top bar writes a portfolio snapshot to a personal spreadsheet in the student's Google Drive. First click creates a "My Stock Tracker" sheet; subsequent clicks append a new row per ISO week or update in place if the same week is saved again. The spreadsheet ID is persisted in the student's GCS profile to avoid needing the Drive API scope. OAuth scope `spreadsheets` added to the consent screen; existing students must re-login once to pick up the new scope.

### Performance
- Both the curfew block and idle disconnect drive idle Cloud Run instances to zero after school hours, cutting idle billable instance time and Cloud Run spend.

## 2026-08-28

### Fixed
- **Market Movers wedged on "Loading market data..."**: the login pre-warm (`_prewarm_movers`) set `_movers_cache["loading"] = True` but never reset it, so `_load_movers()` returned early forever and the movers cache never populated — for every user, since the cache is module-global. Pre-warm now only warms the yfinance TTL cache; `_load_movers` is the sole owner of the loading flag, and `movers_load_action()` classifies the cache as `refresh`/`wait`/`fetch` so concurrent pages wait (bounded 20s) then refresh instead of dead-ending

## 2026-08-27

### Performance
- Thread pool increased from 4 to 16 workers to handle18 simultaneous users
- Added token-bucket rate limiter (`_TokenBucket`) for yfinance calls — capacity 15, rate 8/sec (relaxed from 5/2); all acquires `timeout=3`
- Replaced per-call `ThreadPoolExecutor` in `_portfolio()` with shared `_shared_executor` (8 workers)
- GCS database cached for 60s (`get_gcs_database()` TTL cache)
- GCS HTTP timeouts reduced from 10s to 5s across all 5 calls
- Shared movers cache with 5-min TTL + atomic loading lock
- Eliminated duplicate `fetch_stock_market_data` calls in ticker search (merged `_upd_sel` + `_upd_preview`)
- All `run_in_executor(None, ...)` replaced with `_executor` (zero remaining)

### Fixed
- **Portfolio tab hang from zero-cost "dust" holdings**: a fractional-share sell could leave a residual position with `total_cost == 0` but `shares > 0`, causing `ZeroDivisionError` in `_portfolio()` and freezing the summary bar + Portfolio tab (HJ Yang's LLY, SJ Lee's IVZ). Loaders now skip dust positions, sell-deletion tolerates <1e-6 share residue, and `_clean_dust_holdings()` self-heals on profile load
- **Unsettled cash excluded from net worth**: standings and admin now use `nw = ((cash + unsettled) / 100) + mv` — previously phantom losses after sells
- **Session timeout on idle browsing**: `_tick()` wrapped in try/finally; separate 60s heartbeat timer ensures `_touch_session()` fires independently
- **Async page load**: `_get(email)` wrapped in `run_in_executor` — `main_page()` is now `async def`
- Samsung (`SSNLF`) and SK Hynix (`SKHY`) added to `POPULAR_STOCKS`

### Added
- Admin holdings dialog now shows full trade history (buys green, sells red) with ticker, shares, price, total, cost basis, tax, and timestamp
- 30+ new ETFs: Schwab (SCHB, SCHX, SCHA, SCHF, SCHE, SCHZ), Vanguard (VUG, VTV, VO, VB), iShares (IVV, IJR, IEFA, LQD, TIP, MUB, IBB), Invesco (SPLV, SPHQ, RSP, SPUU, SPXL, SH, SDS, SPXS), Xtrackers/ESG (USSG, ESGU, SUSA, SPLG)
- Multi-select checkboxes + "Remove Selected" button + confirmation dialog for deleting students by name
- `delete_student_profile_by_key()` in `utils/storage.py`
- Google Form questionnaire for students (15 questions)

## 2026-06-10

### Fixed
- NaN close price: `_fetch_stock_market_data_impl` now uses `.dropna().iloc[-1]` instead of `.iloc[-1]`, so today's incomplete trading day (NaN) doesn't break all price fetches
- urllib3 v2 / LibreSSL incompatibility: pinned `urllib3<2` in requirements.txt (macOS ships LibreSSL 2.8.3, urllib3 v2 requires OpenSSL 1.1.1+)
- Removed cdnjs Material Icons fallback (was conflicting with Google Fonts CDN)
- Removed `get_gcs_database()` call from page load warmup (was fetching ALL student profiles from GCS on every login, causing timeout)
- `_fetch_stock_market_data_impl` now tries period fallbacks (5d → 1mo → 6mo) with 15s timeout instead of single 5d/5s attempt
- Pie charts always render "Cash" slice even at $0 (empty positions no longer hides charts entirely)
- Header name/email labels now truncate with ellipsis instead of overlapping the account icon
- Replaced `@ui.page('/callback')` with FastAPI `@app.get('/callback')` to avoid WebSocket disconnect during OAuth exchange
- Added `load_student_profile` var and `warm_price_cache` for batch price fetching
- Added `timeout=5` to all yfinance calls

### Changed
- Merged antigravity's credential file fallbacks (reads `client_secret.json`/service-account JSON from disk if env vars missing)
- Redirect URI auto-detected from request URL instead of env var (fixes redirect_uri_mismatch across environments)

### Added
- Portfolio allocation donut chart (cash vs holdings) at top of Portfolio tab
- Full S&P 500 stock list (503 stocks) plus ETFs replacing curated 50-stock picker
- 50-day SMA overlay on candlestick charts; volume bars colored green/red by daily direction
- 15% profit tax on stock sales (deducted from gains only)
- Weekly $100 deposit for students (accumulates for missed weeks)
- GCS bucket object versioning enabled to preserve student portfolio data through bug fixes
- Initial Streamlit app with Google OAuth login wall
- Google Workspace OAuth integration (confidential client, PKCE disabled)
- Google Cloud Storage persistence for user portfolios
- Trading module (Buy / Sell / Liquidate with $1,000 starting cash)
- Volatility calculator (sample standard deviation of daily returns)
- Live price display via yfinance for each selected stock
- Interactive Plotly candlestick charts with volume bars
- In-app price alerts (triggered on page load)
- Stock picker dropdown with 50+ curated stocks, index funds, sector ETFs, and dividend ETFs
- `requirements.txt` for Streamlit Community Cloud deployment
- `.gitignore` for secrets and build artifacts
- GitHub repo (rpiana133/math_finance_simulator) and Streamlit Cloud deployment

### Changed
- Converted config from local files to `st.secrets` for cloud deployment
- Default redirect URI now points to deployed app URL
- Full stock list used across all tabs (Transaction, Volatility, Chart, Alerts)

### Removed
- AI stock analysis feature (held off per user request)

### Fixed
- OAuth `InvalidGrantError` handling
- `NameError` from helper function being called before definition
- Price fetching broken on Streamlit Cloud after yfinance 1.4.0 introduced MultiIndex columns. Added `_flatten_cols()` helper to strip the ticker level from MultiIndex so column access like `data['Close']` works again.