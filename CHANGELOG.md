# Changelog

## 2026-06-10

### Fixed
- Removed `get_gcs_database()` call from page load warmup (was fetching ALL student profiles from GCS on every login, causing timeout)
- `_fetch_stock_market_data_impl` now tries period fallbacks (5d → 1mo → 6mo) with 15s timeout instead of single 5d/5s attempt
- Added cdnjs fallback for Material Icons font (fixes "arrow_drop_down", "chevron_left" text rendering)
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