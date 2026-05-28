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

from datetime import datetime

# Page Configuration
st.set_page_config(page_title="Classroom Stock Simulator", page_icon="📈", layout="wide")

CUSTOM_CSS = """
<style>
    html, body, [class*="css"] { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    .stApp { background: #f8f9fa; }
    .block-container { padding: 1rem 2rem !important; }
    
    /* All text base - soft dark */
    p, li, .markdown-text-container, .stMarkdown, .stWrite, div {
        color: #2d3748;
    }
    
    /* Top nav bar - light blue */
    .topbar {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        color: #1a202c;
        border: 1px solid #e2e8f0;
    }
    .topbar h1 { margin:0; font-size:1.3rem; font-weight:700; letter-spacing:-0.3px; color:#1a202c; }
    .topbar .user-badge {
        display:flex; align-items:center; gap:8px;
        background: rgba(255,255,255,0.6); padding: 4px 14px; border-radius: 20px;
        font-size:0.85rem; color:#2d3748;
    }
    
    /* Portfolio summary bar */
    .psummary {
        display: flex; gap: 2rem; margin-bottom: 1.2rem;
        background: #ffffff; padding: 1rem 1.5rem; border-radius: 8px;
        border: 1px solid #e2e8f0;
    }
    .psummary .label { font-size:0.75rem; color:#4a5568; text-transform:uppercase; letter-spacing:0.5px; font-weight:600; }
    .psummary .value { font-size:1.5rem; font-weight:700; color:#1a202c; }
    .psummary .value.positive { color:#059669; }
    .psummary .value.negative { color:#dc2626; }
    .psummary .sub { font-size:0.85rem; font-weight:600; }
    .psummary .sub.positive { color:#059669; }
    .psummary .sub.negative { color:#dc2626; }
    
    /* Cards */
    .card {
        background: #ffffff; border-radius: 8px; padding: 1.25rem;
        border: 1px solid #e2e8f0; margin-bottom: 1rem;
    }
    .card h3 { margin:0 0 0.75rem 0; font-size:1rem; font-weight:700; color:#1a202c; }
    
    /* Data table */
    .dataframe { font-size:0.85rem; }
    .stAgGrid, [data-testid="stDataFrame"] { color:#1a202c !important; font-size:0.9rem !important; }
    [data-testid="stDataFrame"] td,
    [data-testid="stDataFrame"] th { color:#1a202c !important; }
    
    /* Metric boxes */
    .metric-row { display:flex; gap:1rem; margin-bottom:1rem; }
    .metric-box {
        background: #ffffff; border-radius:8px; padding:0.75rem 1rem; flex:1;
        border: 1px solid #e2e8f0;
    }
    .metric-box .m-label { font-size:0.75rem; color:#4a5568; text-transform:uppercase; font-weight:600; letter-spacing:0.3px; }
    .metric-box .m-value { font-size:1.1rem; font-weight:700; color:#1a202c; }
    
    /* Buttons */
    .stButton button {
        font-weight:600; border-radius:6px; font-size:0.85rem; color:#1a202c !important;
        transition: all 0.15s ease; border: 1px solid #cbd5e0; background: #ffffff;
    }
    .stButton button:active { transform:scale(0.97); }
    .stButton button[kind="primary"] {
        background: #2563eb; border: 1px solid #2563eb; color: #ffffff !important;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap:0.5rem; background:#ffffff; padding:0.25rem; border-radius:8px; border: 1px solid #e2e8f0; }
    .stTabs [data-baseweb="tab"] { border-radius:6px; font-size:0.85rem; font-weight:500; color:#4a5568 !important; }
    .stTabs [aria-selected="true"] {
        background: transparent !important; color:#1a202c !important; font-weight:600 !important;
        border-bottom: 2px solid #16a34a !important;
    }
    
    /* Selectbox / Input labels */
    .stSelectbox label, .stNumberInput label, .stRadio label {
        color: #2d3748 !important; font-weight:600 !important; font-size:0.85rem !important;
    }
    .stSelectbox div[data-baseweb="select"] span { color:#000000 !important; }
    .stSelectbox div[data-baseweb="select"] {
        background: #ffffff !important; border: 1px solid #cbd5e0 !important; border-radius: 6px !important;
    }
    .stSelectbox div[data-baseweb="select"]:hover { border-color: #9ca3af !important; }
    /* Select dropdown */
    div[data-baseweb="popover"],
    div[data-baseweb="menu"],
    div[role="listbox"], ul[role="listbox"],
    .stSelectbox div[role="listbox"] {
        background: #ffffff !important;
        border: 1px solid #d1d5db !important;
        border-radius: 6px !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important;
        padding: 4px 0 !important;
    }
    div[data-baseweb="popover"] li, div[data-baseweb="menu"] li,
    li[role="option"], div[role="option"] {
        color: #000000 !important; font-size: 0.9rem !important; padding: 8px 12px !important;
        background: #ffffff !important;
    }
    div[data-baseweb="popover"] li:hover, div[data-baseweb="menu"] li:hover,
    li[role="option"]:hover, div[role="option"]:hover,
    [data-baseweb="menu"] [role="option"]:hover { background: #f3f4f6 !important; }
    div[data-baseweb="popover"] li[aria-selected="true"], div[data-baseweb="menu"] li[aria-selected="true"],
    li[role="option"][aria-selected="true"], div[role="option"][aria-selected="true"],
    [data-baseweb="menu"] [role="option"][aria-selected="true"] {
        background: #e5e7eb !important; font-weight:600 !important;
    }

    /* Streamlit 1.40+ select widget */
    .stSelectbox [class*="list"],
    .stSelectbox [class*="menu"],
    .stSelectbox [class*="dropdown"],
    .stSelectbox [class*="option"],
    .stSelectbox [class*="select"] > [class*="container"] {
        background: #ffffff !important;
        color: #000000 !important;
    }

    /* Native select fallback */
    .stSelectbox select, .stSelectbox select option {
        background: #ffffff !important;
        color: #000000 !important;
    }
    .stSelectbox select {
        border: 1px solid #cbd5e0 !important;
        border-radius: 6px !important;
        padding: 4px 8px !important;
    }

    /* Dark mode override */
    [data-theme="dark"] .stSelectbox * {
        background: #ffffff !important;
        color: #000000 !important;
    }
    
    /* Number input */
    .stNumberInput input {
        background: #ffffff !important; border: 1px solid #cbd5e0 !important;
        border-radius: 6px !important; color: #000000 !important;
    }
    .stNumberInput input:focus { border-color: #2563eb !important; box-shadow: 0 0 0 2px rgba(37,99,235,0.15) !important; }
    
    /* Info / Warning / Error boxes */
    .stAlert { border-left: 4px solid; }
    .stAlert p { color: #2d3748 !important; }
    
    /* Caption text */
    .stCaption, .element-container div.small-font, [data-testid="stCaption"] {
        color: #4a5568 !important; font-size:0.8rem !important;
    }
    
    /* Dividers */
    .stDivider { margin:1rem 0; }
    
    /* Hide default streamlit header */
    #MainMenu {visibility:hidden;} footer {visibility:hidden;}
</style>"""

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
        "alerts": [],
        "history": []
    }
    save_gcs_database(global_database)

student_profile = global_database[student_email]
student_cash = student_profile["cash"]
student_holdings = student_profile["holdings"]
student_alerts = student_profile.get("alerts", [])
student_history = student_profile.get("history", [])

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
    "SDY": "S&P Dividend ETF", "DVY": "Select Dividend ETF",
    "BOTZ": "Global X Robotics & AI ETF",
    "AIQ": "Global X AI & Tech ETF",
    "ROBT": "First Trust Nasdaq AI & Robotics ETF",
    "ROBO": "Robo Global Robotics & AI ETF",
    "ARKQ": "ARK Autonomous Tech & Robotics ETF",
    "ARKW": "ARK Next Gen Internet ETF",
    "AIEQ": "Amplify AI Powered Equity ETF",
    "CHAT": "Roundhill Generative AI ETF",
    "SMH": "VanEck Semiconductor ETF",
    "SOXX": "iShares Semiconductor ETF",
    "SOXQ": "Invesco Semiconductor ETF",
    "PSI": "Invesco Dynamic Semiconductors ETF"
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

CHART_PERIODS = {
    "1d": "1 Day", "5d": "5 Days", "1mo": "1 Month", "3mo": "3 Months",
    "6mo": "6 Months", "1y": "1 Year", "5y": "5 Years", "max": "Max"
}

@st.cache_data(ttl=600)
def fetch_stock_market_data(ticker):
    try:
        data = yf.download(ticker, period="1y", progress=False)
        if data.empty:
            print(f"fetch_stock_market_data: 1y empty for {ticker}, trying 6mo")
            data = yf.download(ticker, period="6mo", progress=False)
        if data.empty:
            print(f"fetch_stock_market_data: 6mo empty for {ticker}, trying 1mo")
            data = yf.download(ticker, period="1mo", progress=False)
        if data.empty:
            print(f"fetch_stock_market_data: all periods empty for {ticker}")
            return None, None, None
        close_price = float(data['Close'].iloc[-1])
        try:
            info = yf.Ticker(ticker).info
            company_name = info.get('shortName') or info.get('longName') or ticker
        except Exception:
            company_name = ticker
        recent = data.tail(10) if len(data) >= 10 else data
        return close_price, recent, company_name
    except Exception as e:
        print(f"fetch_stock_market_data error for {ticker}: {e}")
        return None, None, None

@st.cache_data(ttl=600)
def fetch_full_history(ticker, period="3mo"):
    try:
        data = yf.download(ticker, period=period, progress=False)
        if data.empty:
            print(f"fetch_full_history: {period} empty for {ticker}")
            return None
        return data
    except Exception as e:
        print(f"fetch_full_history error for {ticker}: {e}")
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

def plot_candlestick(ticker, hist, period_label="3 Months"):
    period_text = f" ({period_label})" if period_label else ""
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
        title=f"{ticker}{period_text}",
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
    <h1>📈 Math Finance Simulator</h1>
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
    
    if student_history:
        st.markdown('<div class="card"><h3>Trade History</h3>', unsafe_allow_html=True)
        hist_df = pd.DataFrame(reversed(student_history))
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
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
        order_mode = st.radio("Order Type", ["By Shares", "By Amount ($)"], horizontal=True)
        
        if order_mode == "By Shares":
            shares_input = st.number_input("Shares", min_value=0.001, value=1.0, step=0.1, format="%.4f")
            usd_allocation = shares_input * live_price if live_price else 0
            if live_price:
                st.caption(f"≈ ${usd_allocation:,.2f}")
        else:
            usd_allocation = st.number_input("Amount ($)", min_value=1.00, value=100.00, step=10.00)
            if live_price:
                st.caption(f"≈ {usd_allocation / live_price:.4f} shares")
        
        if st.button("Submit Order", type="primary", use_container_width=True):
            live_price, _, company = fetch_stock_market_data(trade_ticker)
            if live_price is None:
                st.error(f"Ticker '{trade_ticker}' not found.")
            else:
                if order_mode == "By Shares":
                    shares_to_trade = shares_input
                    actual_cost = shares_to_trade * live_price
                else:
                    shares_to_trade = usd_allocation / live_price
                    actual_cost = usd_allocation
                
                if action == "Buy":
                    if actual_cost > student_cash:
                        st.error("Insufficient cash.")
                    else:
                        student_profile["cash"] = round(student_cash - actual_cost, 2)
                        if trade_ticker in student_holdings:
                            student_holdings[trade_ticker]['shares'] += shares_to_trade
                            student_holdings[trade_ticker]['total_cost'] += actual_cost
                        else:
                            student_holdings[trade_ticker] = {'shares': shares_to_trade, 'total_cost': actual_cost}
                        student_profile.setdefault("history", []).append({
                            "type": "Buy", "ticker": trade_ticker, "shares": round(shares_to_trade, 4),
                            "price": round(live_price, 2), "total": round(actual_cost, 2),
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M")
                        })
                        global_database[student_email] = student_profile
                        save_gcs_database(global_database)
                        st.success(f"Bought {shares_to_trade:.4f} shares of {trade_ticker}!")
                        st.rerun()
                elif action == "Sell":
                    if trade_ticker not in student_holdings:
                        st.error("Asset not owned.")
                    else:
                        owned_shares = student_holdings[trade_ticker]['shares']
                        if order_mode == "By Shares":
                            if shares_input > owned_shares + 0.0001:
                                st.error("Not enough shares owned.")
                            else:
                                sell_shares = shares_input
                                sell_value = sell_shares * live_price
                                fraction_sold = sell_shares / owned_shares
                                student_profile["cash"] = round(student_cash + sell_value, 2)
                                student_holdings[trade_ticker]['shares'] -= sell_shares
                                student_holdings[trade_ticker]['total_cost'] -= fraction_sold * student_holdings[trade_ticker]['total_cost']
                                if student_holdings[trade_ticker]['shares'] < 0.0001:
                                    del student_holdings[trade_ticker]
                                student_profile.setdefault("history", []).append({
                                    "type": "Sell", "ticker": trade_ticker, "shares": round(sell_shares, 4),
                                    "price": round(live_price, 2), "total": round(sell_value, 2),
                                    "time": datetime.now().strftime("%Y-%m-%d %H:%M")
                                })
                                global_database[student_email] = student_profile
                                save_gcs_database(global_database)
                                st.success(f"Sold {sell_shares:.4f} shares of {trade_ticker}!")
                                st.rerun()
                        else:
                            current_position_value = owned_shares * live_price
                            if usd_allocation > (current_position_value + 0.01):
                                st.error("Amount exceeds position value.")
                            else:
                                fraction_sold = usd_allocation / current_position_value
                                sell_shares = fraction_sold * owned_shares
                                student_profile["cash"] = round(student_cash + usd_allocation, 2)
                                student_holdings[trade_ticker]['shares'] -= sell_shares
                                student_holdings[trade_ticker]['total_cost'] -= fraction_sold * student_holdings[trade_ticker]['total_cost']
                                if student_holdings[trade_ticker]['shares'] < 0.0001:
                                    del student_holdings[trade_ticker]
                                student_profile.setdefault("history", []).append({
                                    "type": "Sell", "ticker": trade_ticker, "shares": round(sell_shares, 4),
                                    "price": round(live_price, 2), "total": round(usd_allocation, 2),
                                    "time": datetime.now().strftime("%Y-%m-%d %H:%M")
                                })
                                global_database[student_email] = student_profile
                                save_gcs_database(global_database)
                                st.success(f"Sold ${usd_allocation:,.2f} of {trade_ticker}!")
                                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tcol2:
        st.markdown('<div class="card" style="padding:0.5rem 1.25rem 1.25rem 1.25rem;">', unsafe_allow_html=True)
        trade_chart_period = st.selectbox("Period", options=list(CHART_PERIODS.keys()), format_func=lambda k: CHART_PERIODS[k], key="trade_chart_period", label_visibility="collapsed")
        chart_trade_ticker = parse_ticker_option(selected_display)
        hist = fetch_full_history(chart_trade_ticker, period=trade_chart_period)
        if hist is not None and len(hist) > 5:
            fig = plot_candlestick(chart_trade_ticker, hist, period_label=CHART_PERIODS[trade_chart_period])
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
        research_chart_period = st.selectbox("Period", options=list(CHART_PERIODS.keys()), format_func=lambda k: CHART_PERIODS[k], key="research_chart_period", label_visibility="collapsed")
        hist2 = fetch_full_history(chart_ticker2, period=research_chart_period)
        if hist2 is not None and len(hist2) > 5:
            fig2 = plot_candlestick(chart_ticker2, hist2, period_label=CHART_PERIODS[research_chart_period])
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
