# Changelog

## 2026-05-28

### Added
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
