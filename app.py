import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.cloud import storage
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Page Configuration
st.set_page_config(page_title="Classroom Stock Simulator", page_icon="📈", layout="wide")

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; }
    .stApp { background: #f0f2f5; }
    .block-container { padding: 1rem 2rem !important; }
    
    /* Top nav bar */
    .topbar {
        background: linear-gradient(135deg, #1a3a5c 0%, #0d2137 100%);
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        color: white;
    }
    .topbar h1 { margin:0; font-size:1.3rem; font-weight:600; letter-spacing:-0.3px; }
    .topbar .user-badge {
        display:flex; align-items:center; gap:8px;
        background: rgba(255,255,255,0.1); padding: 4px 12px; border-radius: 20px;
        font-size:0.85rem;
    }
    
    /* Portfolio summary bar */
    .psummary {
        display: flex; gap: 2rem; margin-bottom: 1.2rem;
        background: white; padding: 1rem 1.5rem; border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .psummary .item { }
    .psummary .label { font-size:0.75rem; color:#6b7280; text-transform:uppercase; letter-spacing:0.5px; font-weight:500; }
    .psummary .value { font-size:1.5rem; font-weight:700; color:#111827; }
    .psummary .value.positive { color:#16a34a; }
    .psummary .value.negative { color:#dc2626; }
    .psummary .sub { font-size:0.85rem; font-weight:500; }
    .psummary .sub.positive { color:#16a34a; }
    .psummary .sub.negative { color:#dc2626; }
    
    /* Cards */
    .card {
        background: white; border-radius: 8px; padding: 1.25rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 1rem;
    }
    .card h3 { margin:0 0 0.75rem 0; font-size:1rem; font-weight:600; color:#1f2937; }
    
    /* Data table styling */
    .dataframe { font-size:0.85rem; }
    
    /* Metric boxes */
    .metric-row { display:flex; gap:1rem; margin-bottom:1rem; }
    .metric-box {
        background: white; border-radius:8px; padding:0.75rem 1rem; flex:1;
        box-shadow:0 1px 3px rgba(0,0,0,0.08);
    }
    .metric-box .m-label { font-size:0.75rem; color:#6b7280; text-transform:uppercase; font-weight:500; letter-spacing:0.3px; }
    .metric-box .m-value { font-size:1.1rem; font-weight:700; color:#111827; }
    
    /* Buttons */
    .stButton button {
        font-weight:600; border-radius:6px; font-size:0.85rem;
        transition: all 0.15s ease;
    }
    .stButton button:active { transform:scale(0.97); }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap:0.5rem; background:white; padding:0.25rem; border-radius:8px; }
    .stTabs [data-baseweb="tab"] { border-radius:6px; font-size:0.85rem; font-weight:500; }
    
    /* Dividers */
    .stDivider { margin:1rem 0; }
    
    /* Hide default streamlit header */
    #MainMenu {visibility:hidden;} footer {visibility:hidden;}
</style>
"""

# ==========================================
# 1. GOOGLE OAUTH2 AUTHENTICATION GATING
# ==========================================
SCOPES = [
    'https://www.googleapis.com/auth/classroom.coursework.students',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]

# Determine redirect URI (local dev vs deployed)
REDIRECT_URI = st.secrets.get("REDIRECT_URI", "https://mathfinancesimulator.streamlit.app/")

if 'credentials' not in st.session_state:
    st.session_state.credentials = None
if 'user_info' not in st.session_state:
    st.session_state.user_info = None

def get_client_config():
    return json.loads(st.secrets["GOOGLE_CLIENT_SECRET"])

def do_login():
    client_config = get_client_config()
    flow = Flow.from_client_config(
        client_config, scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.markdown(f"### [🔗 Click Here to Sign in with Google Workspace]({auth_url})")

def handle_redirect():
    query_params = st.query_params
    if 'code' in query_params:
        client_config = get_client_config()
        flow = Flow.from_client_config(
            client_config, scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        flow.autogenerate_code_verifier = False
        flow.code_verifier = None
        flow.fetch_token(code=query_params['code'])
        st.session_state.credentials = flow.credentials

        user_info_service = build('oauth2', 'v2', credentials=flow.credentials)
        st.session_state.user_info = user_info_service.userinfo().get().execute()

        st.query_params.clear()
        st.rerun()

# Execute Login Wall
if st.session_state.credentials is None:
    st.title("🧮 Math Simulator Login")
    try:
        _ = get_client_config()
    except (KeyError, json.JSONDecodeError):
        st.warning("⚠️ **Setup Required:** Set `GOOGLE_CLIENT_SECRET` in Streamlit Cloud secrets.")
        st.stop()
    handle_redirect()
    if st.session_state.credentials is None:
        do_login()
        st.stop()

# ==========================================
# 2. GOOGLE CLOUD STORAGE SYSTEM (DATA LAYER)
# ==========================================
# REPLACE THIS WITH YOUR ACTUAL GOOGLE CLOUD STORAGE BUCKET NAME
GCS_BUCKET_NAME = "math_finance_simulator" 
BLOB_NAME = "classroom_portfolios.json"
student_email = st.session_state.user_info['email']

def get_gcs_client():
    key_info = json.loads(st.secrets["GCS_SERVICE_ACCOUNT"])
    creds = service_account.Credentials.from_service_account_info(key_info)
    return storage.Client(credentials=creds, project=key_info.get("project_id"))

def get_gcs_database():
    """Fetches the global student portfolio database ledger from Google Cloud Storage."""
    try:
        storage_client = get_gcs_client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(BLOB_NAME)
        
        if not blob.exists():
            return {}
        
        data = blob.download_as_text()
        return json.loads(data)
    except Exception:
        # Fallback cache to keep app operational if bucket permissions are still propagating
        if 'fallback_db' not in st.session_state:
            st.session_state.fallback_db = {}
        return st.session_state.fallback_db

def save_gcs_database(db_data):
    """Saves the updated database ledger back up to Google Cloud Storage."""
    try:
        storage_client = get_gcs_client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(BLOB_NAME)
        blob.upload_from_string(json.dumps(db_data, indent=4), content_type='application/json')
    except Exception:
        st.session_state.fallback_db = db_data

# Extract or Initialize this specific student's cloud profile
global_database = get_gcs_database()
if student_email not in global_database:
    global_database[student_email] = {
        "name": st.session_state.user_info.get('name', 'Student'),
        "cash": 1000.00,
        "holdings": {},
        "alerts": []
    }
    save_gcs_database(global_database)

student_profile = global_database[student_email]
student_cash = student_profile["cash"]
student_holdings = student_profile["holdings"]
student_alerts = student_profile.get("alerts", [])

# ==========================================
# 3. STOCK DATA & REAL-TIME MATHEMATICS ENGINE
# ==========================================
POPULAR_STOCKS = {
    "AAPL": "Apple Inc.", "MSFT": "Microsoft", "GOOGL": "Alphabet (Google)",
    "AMZN": "Amazon", "NVDA": "NVIDIA", "META": "Meta (Facebook)",
    "TSLA": "Tesla", "BRK-B": "Berkshire Hathaway", "JPM": "JPMorgan Chase",
    "V": "Visa", "JNJ": "Johnson & Johnson", "WMT": "Walmart",
    "MA": "Mastercard", "PG": "Procter & Gamble", "UNH": "UnitedHealth",
    "HD": "Home Depot", "DIS": "Disney", "BAC": "Bank of America",
    "NFLX": "Netflix", "ADBE": "Adobe", "CRM": "Salesforce",
    "PEP": "PepsiCo", "KO": "Coca-Cola", "INTC": "Intel",
    "AMD": "AMD", "PYPL": "PayPal", "UBER": "Uber",
    "SQ": "Block (Square)", "SNAP": "Snapchat", "PLTR": "Palantir",
    "SPY": "S&P 500 ETF", "QQQ": "Nasdaq 100 ETF", "IWM": "Russell 2000 ETF",
    "DIA": "Dow Jones ETF", "VTI": "Total Stock Market ETF",
    "VOO": "S&P 500 ETF (Vanguard)", "BND": "Total Bond Market ETF",
    "GLD": "Gold ETF", "SLV": "Silver ETF", "EEM": "Emerging Markets ETF",
    "XLF": "Financial Sector ETF", "XLK": "Tech Sector ETF",
    "XLV": "Healthcare Sector ETF", "XLE": "Energy Sector ETF",
    "SCHD": "Dividend Equity ETF", "VIG": "Dividend Appreciation ETF",
    "VYM": "High Dividend Yield ETF", "DGRO": "Dividend Growth ETF",
    "SPYD": "S&P 500 High Dividend ETF", "NOBL": "Dividend Aristocrats ETF",
    "SDY": "S&P Dividend ETF", "DVY": "Select Dividend ETF"
}

ALL_TICKERS = list(POPULAR_STOCKS.keys())

def get_company_name(ticker):
    return POPULAR_STOCKS.get(ticker, ticker)

def format_ticker_option(ticker):
    name = POPULAR_STOCKS.get(ticker)
    if name:
        return f"{ticker} — {name}"
    return ticker

def parse_ticker_option(display_str):
    return display_str.split(" —")[0].strip()

DISPLAY_OPTIONS = [format_ticker_option(t) for t in ALL_TICKERS]

@st.cache_data(ttl=60)
def fetch_stock_market_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        live_price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        company_name = info.get('shortName') or info.get('longName') or ticker
        if live_price:
            hist = stock.history(period="1mo")
            if not hist.empty:
                return float(live_price), hist.tail(10), company_name
        for period in ["5d", "1d"]:
            hist = stock.history(period=period)
            if not hist.empty:
                return float(hist['Close'].iloc[-1]), hist.tail(10), company_name
        return None, None, None
    except Exception:
        return None, None, None

@st.cache_data(ttl=300)
def fetch_full_history(ticker, period="3mo"):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        if hist.empty:
            return None
        return hist
    except Exception:
        return None

total_holding_value = 0.0
live_portfolio_data = []

for ticker, position in list(student_holdings.items()):
    live_price, _, _ = fetch_stock_market_data(ticker)
    if live_price is not None:
        current_val = position['shares'] * live_price
        total_holding_value += current_val
        avg_purchase_price = position['total_cost'] / position['shares']
        pct_return = ((live_price - avg_purchase_price) / avg_purchase_price) * 100
        
        live_portfolio_data.append({
            "Ticker": ticker,
            "Shares": round(position['shares'], 4),
            "Avg Purchase Price": f"${avg_purchase_price:.2f}",
            "Live Price": f"${live_price:.2f}",
            "Total Value": f"${current_val:.2f}",
            "Percentage Return": f"{pct_return:+.2f}%"
        })

total_portfolio_value = student_cash + total_holding_value
total_pl_dollars = total_portfolio_value - 1000.00
total_pl_pct = ((total_portfolio_value - 1000.00) / 1000.00) * 100
pl_class = "positive" if total_pl_dollars >= 0 else "negative"

# ==========================================
# 5. ALERT CHECKING
# ==========================================
def check_and_trigger_alerts():
    triggered = []
    for alert in student_alerts:
        ticker = alert["ticker"]
        price, _, _ = fetch_stock_market_data(ticker)
        if price is None:
            continue
        direction = alert["direction"]
        target = alert["price"]
        if direction == "above" and price >= target:
            triggered.append(f"{ticker} hit ${price:.2f} (above ${target:.2f})")
        elif direction == "below" and price <= target:
            triggered.append(f"{ticker} dropped to ${price:.2f} (below ${target:.2f})")
    return triggered

triggered_alerts = check_and_trigger_alerts()

def plot_candlestick(ticker, hist):
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.7, 0.3]
    )
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist['Open'], high=hist['High'],
        low=hist['Low'], close=hist['Close'], name=ticker,
        increasing_line_color='#16a34a', decreasing_line_color='#dc2626'
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=hist.index, y=hist['Volume'], name='Volume',
        marker_color='rgba(107,114,128,0.4)', showlegend=False
    ), row=2, col=1)
    fig.update_layout(
        title=f"{ticker} — 3 Month",
        xaxis_title=None, yaxis_title="Price ($)",
        height=500, margin=dict(l=0, r=0, t=35, b=0),
        template="none",
        hovermode="x unified",
        font=dict(family="Inter, -apple-system, sans-serif", size=11),
        paper_bgcolor='white', plot_bgcolor='white'
    )
    fig.update_xaxes(rangeslider_visible=False, gridcolor='#f0f2f5', zerolinecolor='#e5e7eb')
    fig.update_yaxes(gridcolor='#f0f2f5', zerolinecolor='#e5e7eb')
    return fig

# ==========================================
# 4. USER INTERFACE (FIDELITY-INSPIRED)
# ==========================================
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Top nav bar
st.markdown(f"""
<div class="topbar">
    <h1>📈 MathFin Simulator</h1>
    <div class="user-badge">
        <span>👤 {student_profile['name']}</span>
        <span style="opacity:0.6">|</span>
        <span style="font-size:0.8rem">{student_email}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Portfolio summary bar
st.markdown(f"""
<div class="psummary">
    <div class="item">
        <div class="label">Cash Balance</div>
        <div class="value">${student_cash:,.2f}</div>
    </div>
    <div class="item">
        <div class="label">Portfolio Value</div>
        <div class="value">${total_holding_value:,.2f}</div>
    </div>
    <div class="item">
        <div class="label">Total Account</div>
        <div class="value">${total_portfolio_value:,.2f}</div>
        <div class="sub {pl_class}">{"+" if total_pl_dollars >= 0 else ""}${total_pl_dollars:,.2f} ({total_pl_pct:+.2f}%)</div>
    </div>
</div>
""", unsafe_allow_html=True)

# Alert notifications
if triggered_alerts:
    for alert_msg in triggered_alerts:
        st.warning(f"🔔 {alert_msg}")

# Main tabs
main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs(["📋 Portfolio", "🪙 Trade", "🔬 Research", "🔔 Alerts"])

with main_tab1:
    st.markdown('<div class="card"><h3>Positions</h3>', unsafe_allow_html=True)
    if live_portfolio_data:
        df = pd.DataFrame(live_portfolio_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No open positions. Use the Trade tab to allocate your $1,000 starting capital.")
    st.markdown('</div>', unsafe_allow_html=True)

with main_tab2:
    tcol1, tcol2 = st.columns([1, 1.4])
    
    with tcol1:
        st.markdown('<div class="card"><h3>Trade Ticket</h3>', unsafe_allow_html=True)
        selected_display = st.selectbox("Symbol", options=DISPLAY_OPTIONS, index=0, label_visibility="collapsed")
        trade_ticker = parse_ticker_option(selected_display)
        
        live_price, _, company = fetch_stock_market_data(trade_ticker)
        
        if live_price is not None:
            st.markdown(f"""
            <div style="margin:-0.5rem 0 0.5rem 0; font-size:0.85rem; color:#374151;">
                {company} · <strong>${live_price:.2f}</strong>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning(f"Price unavailable for {trade_ticker}")
        
        action = st.radio("Action", ["Buy", "Sell"], horizontal=True)
        usd_allocation = st.number_input("Amount ($)", min_value=1.00, value=100.00, step=10.00)
        
        if live_price is not None:
            st.caption(f"≈ {usd_allocation / live_price:.4f} shares")
        
        if st.button("Submit Order", type="primary", use_container_width=True):
            live_price, _, company = fetch_stock_market_data(trade_ticker)
            if live_price is None:
                st.error(f"Ticker '{trade_ticker}' not found.")
            else:
                shares_to_trade = usd_allocation / live_price
                if action == "Buy":
                    if usd_allocation > student_cash:
                        st.error("Insufficient cash.")
                    else:
                        student_profile["cash"] = round(student_cash - usd_allocation, 2)
                        if trade_ticker in student_holdings:
                            student_holdings[trade_ticker]['shares'] += shares_to_trade
                            student_holdings[trade_ticker]['total_cost'] += usd_allocation
                        else:
                            student_holdings[trade_ticker] = {'shares': shares_to_trade, 'total_cost': usd_allocation}
                        global_database[student_email] = student_profile
                        save_gcs_database(global_database)
                        st.success(f"Bought ${usd_allocation:,.2f} of {trade_ticker}!")
                        st.rerun()
                elif action == "Sell":
                    if trade_ticker not in student_holdings:
                        st.error("Asset not owned.")
                    else:
                        owned_shares = student_holdings[trade_ticker]['shares']
                        current_position_value = owned_shares * live_price
                        if usd_allocation > (current_position_value + 0.01):
                            st.error("Amount exceeds position value.")
                        else:
                            fraction_sold = usd_allocation / current_position_value
                            student_profile["cash"] = round(student_cash + usd_allocation, 2)
                            student_holdings[trade_ticker]['shares'] -= (fraction_sold * owned_shares)
                            student_holdings[trade_ticker]['total_cost'] -= (fraction_sold * student_holdings[trade_ticker]['total_cost'])
                            if student_holdings[trade_ticker]['shares'] < 0.0001:
                                del student_holdings[trade_ticker]
                            global_database[student_email] = student_profile
                            save_gcs_database(global_database)
                            st.success(f"Sold ${usd_allocation:,.2f} of {trade_ticker}!")
                            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tcol2:
        st.markdown('<div class="card" style="padding:0.5rem 1.25rem 1.25rem 1.25rem;">', unsafe_allow_html=True)
        st.caption("Chart")
        chart_trade_ticker = parse_ticker_option(selected_display)
        hist = fetch_full_history(chart_trade_ticker)
        if hist is not None and len(hist) > 5:
            fig = plot_candlestick(chart_trade_ticker, hist)
            fig.update_layout(height=380, margin=dict(l=0, r=0, t=25, b=0))
            st.plotly_chart(fig, use_container_width=True, key="trade_chart")
        else:
            st.info("Not enough data to chart.")
        st.markdown('</div>', unsafe_allow_html=True)

with main_tab3:
    rcol1, rcol2 = st.columns([1, 1])
    
    with rcol1:
        st.markdown('<div class="card"><h3>Volatility Calculator</h3>', unsafe_allow_html=True)
        vol_display = st.selectbox("Asset", options=DISPLAY_OPTIONS, key="vol_ticker", label_visibility="collapsed")
        vol_ticker = parse_ticker_option(vol_display)
        _, hist_vol, _ = fetch_stock_market_data(vol_ticker)
        if hist_vol is not None and len(hist_vol) >= 2:
            hist_vol['Daily Change (%)'] = hist_vol['Close'].pct_change() * 100
            clean = hist_vol[['Close', 'Daily Change (%)']].dropna()
            std = clean['Daily Change (%)'].std()
            st.markdown(f"""
            <div class="metric-row">
                <div class="metric-box">
                    <div class="m-label">Sample Std Dev</div>
                    <div class="m-value">{std:.4f}%</div>
                </div>
                <div class="metric-box">
                    <div class="m-label">Period</div>
                    <div class="m-value">1 Month</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("Need 2+ data points.")
        st.markdown('</div>', unsafe_allow_html=True)
    
    with rcol2:
        st.markdown('<div class="card"><h3>Price History</h3>', unsafe_allow_html=True)
        chart_display = st.selectbox("Asset", options=DISPLAY_OPTIONS, key="chart_ticker", label_visibility="collapsed")
        chart_ticker2 = parse_ticker_option(chart_display)
        hist2 = fetch_full_history(chart_ticker2)
        if hist2 is not None and len(hist2) > 5:
            fig2 = plot_candlestick(chart_ticker2, hist2)
            fig2.update_layout(height=380, margin=dict(l=0, r=0, t=25, b=0))
            st.plotly_chart(fig2, use_container_width=True, key="research_chart")
        else:
            st.info("Not enough historical data.")
        st.markdown('</div>', unsafe_allow_html=True)

with main_tab4:
    st.markdown('<div class="card"><h3>Price Alerts</h3>', unsafe_allow_html=True)
    st.caption("Notify when a stock crosses a target price.")
    arow1, arow2, arow3, arow4 = st.columns([2, 1, 1, 1])
    with arow1:
        alert_selected = st.selectbox("Symbol", options=DISPLAY_OPTIONS, key="alert_sel", label_visibility="collapsed")
        alert_ticker = parse_ticker_option(alert_selected)
    with arow2:
        alert_direction = st.selectbox("Above/Below", ["above", "below"], key="alert_dir", label_visibility="collapsed")
    with arow3:
        alert_price = st.number_input("Price", min_value=0.01, value=200.00, step=1.0, key="alert_price", label_visibility="collapsed")
    with arow4:
        st.write("&nbsp;")
        if st.button("+ Add", type="primary", use_container_width=True):
            new_alert = {"ticker": alert_ticker, "direction": alert_direction, "price": alert_price}
            student_alerts.append(new_alert)
            student_profile["alerts"] = student_alerts
            global_database[student_email] = student_profile
            save_gcs_database(global_database)
            st.success(f"Alert set!")
            st.rerun()
    if student_alerts:
        st.markdown("<hr style='margin:0.75rem 0'>", unsafe_allow_html=True)
        for i, alert in enumerate(student_alerts):
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            c1.write(alert["ticker"])
            c2.write(f"→ {alert['direction']}")
            c3.write(f"${alert['price']:.2f}")
            if c4.button("✕", key=f"del_alert_{i}", use_container_width=True):
                student_alerts.pop(i)
                student_profile["alerts"] = student_alerts
                global_database[student_email] = student_profile
                save_gcs_database(global_database)
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
