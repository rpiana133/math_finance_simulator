# Changelog

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