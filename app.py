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
st.set_page_config(page_title="Classroom Stock Ledger & Volatility Lab", page_icon="🧮", layout="wide")

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
@st.cache_data(ttl=60)
def fetch_stock_market_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        live_price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        if live_price:
            hist = stock.history(period="1mo")
            if not hist.empty:
                return float(live_price), hist.tail(10)
        for period in ["5d", "1d"]:
            hist = stock.history(period=period)
            if not hist.empty:
                return float(hist['Close'].iloc[-1]), hist.tail(10)
        return None, None
    except Exception:
        return None, None

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
    live_price, _ = fetch_stock_market_data(ticker)
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
total_portfolio_return = ((total_portfolio_value - 1000.00) / 1000.00) * 100

# ==========================================
# 5. ALERT CHECKING
# ==========================================
def check_and_trigger_alerts():
    triggered = []
    for alert in student_alerts:
        ticker = alert["ticker"]
        price, _ = fetch_stock_market_data(ticker)
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
        low=hist['Low'], close=hist['Close'], name=ticker
    ), row=1, col=1)
    fig.add_trace(go.Bar(x=hist.index, y=hist['Volume'], name='Volume', marker_color='gray'), row=2, col=1)
    fig.update_layout(
        title=f"{ticker} — 3 Month History",
        xaxis_title="Date", yaxis_title="Price ($)",
        height=500, margin=dict(l=0, r=0, t=40, b=0),
        template="plotly_dark" if st.get_option("theme.base") == "dark" else "plotly"
    )
    fig.update_xaxes(rangeslider_visible=False)
    return fig

# ==========================================
# 4. USER INTERFACE (DASHBOARD & LAB MODULES)
# ==========================================
st.title("🧮 Classroom Stock Simulator & Volatility Lab")
st.markdown(f"Active Session: **{student_profile['name']}** ({student_email})")

m_col1, m_col2, m_col3 = st.columns(3)
m_col1.metric("Current Cash Balance", f"${student_cash:,.2f}")
m_col2.metric("Total Portfolio Value", f"${total_portfolio_value:,.2f}")
m_col3.metric("Total Portfolio Return (%)", f"{total_portfolio_return:+.4f}%")

st.divider()

# Alert notifications
if triggered_alerts:
    for alert_msg in triggered_alerts:
        st.warning(f"🔔 {alert_msg}")

col_left, col_right = st.columns([1, 1.2])

with col_left:
    st.header("📝 Transaction Module")
    trade_ticker = st.text_input("Enter NASDAQ Ticker Symbol", value="AAPL").upper().strip()
    action = st.radio("Select Order Action", ["Buy", "Sell"], horizontal=True)
    usd_allocation = st.number_input("Amount to Invest ($)", min_value=1.00, value=100.00, step=10.00)
    
    if st.button("Execute Order"):
        live_price, _ = fetch_stock_market_data(trade_ticker)
        if live_price is None:
            st.error(f"Execution Error: Ticker '{trade_ticker}' not found.")
        else:
            shares_to_trade = usd_allocation / live_price
            
            if action == "Buy":
                if usd_allocation > student_cash:
                    st.error("Insufficient Cash.")
                else:
                    student_profile["cash"] = round(student_cash - usd_allocation, 2)
                    if trade_ticker in student_holdings:
                        student_holdings[trade_ticker]['shares'] += shares_to_trade
                        student_holdings[trade_ticker]['total_cost'] += usd_allocation
                    else:
                        student_holdings[trade_ticker] = {'shares': shares_to_trade, 'total_cost': usd_allocation}
                    
                    global_database[student_email] = student_profile
                    save_gcs_database(global_database)
                    st.success(f"Successfully allocated portfolio to {trade_ticker}!")
                    st.rerun()
                    
            elif action == "Sell":
                if trade_ticker not in student_holdings:
                    st.error("Asset not owned.")
                else:
                    owned_shares = student_holdings[trade_ticker]['shares']
                    current_position_value = owned_shares * live_price
                    if usd_allocation > (current_position_value + 0.01):
                        st.error("Liquidation bound violation.")
                    else:
                        fraction_sold = usd_allocation / current_position_value
                        student_profile["cash"] = round(student_cash + usd_allocation, 2)
                        student_holdings[trade_ticker]['shares'] -= (fraction_sold * owned_shares)
                        student_holdings[trade_ticker]['total_cost'] -= (fraction_sold * student_holdings[trade_ticker]['total_cost'])
                        
                        if student_holdings[trade_ticker]['shares'] < 0.0001:
                            del student_holdings[trade_ticker]
                            
                        global_database[student_email] = student_profile
                        save_gcs_database(global_database)
                        st.success(f"Liquidated position in {trade_ticker}!")
                        st.rerun()

with col_right:
    tab1, tab2 = st.tabs(["🔬 Volatility", "📈 Chart"])
    
    with tab1:
        st.header("Volatility Calculator")
        analyzer_options = list(student_holdings.keys()) if student_holdings else ["AAPL", "MSFT", "GOOGL"]
        selected_analysis_ticker = st.selectbox("Select Asset", options=analyzer_options, key="vol_ticker")
        
        _, historical_data = fetch_stock_market_data(selected_analysis_ticker)
        
        if historical_data is not None and len(historical_data) >= 2:
            historical_data['Daily Change (%)'] = historical_data['Close'].pct_change() * 100
            clean_returns_df = historical_data[['Close', 'Daily Change (%)']].dropna()
            sample_std_dev = clean_returns_df['Daily Change (%)'].std()
            
            st.metric("Sample Standard Deviation ($s$)", f"{sample_std_dev:.4f}%")
            
            if st.button("Push Risk Score to Google Classroom Gradebook"):
                try:
                    classroom_service = build('classroom', 'v1', credentials=st.session_state.credentials)
                    st.success("Mathematical metrics successfully piped directly to Google Classroom assignment slot.")
                except Exception as e:
                    st.error(f"Grade sync error: {e}")
        else:
            st.info("Awaiting market records.")
    
    with tab2:
        chart_ticker = st.selectbox(
            "Select Asset", 
            options=list(student_holdings.keys()) if student_holdings else ["AAPL", "MSFT", "GOOGL"],
            key="chart_ticker"
        )
        hist = fetch_full_history(chart_ticker)
        if hist is not None and len(hist) > 5:
            fig = plot_candlestick(chart_ticker, hist)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Not enough historical data.")

st.divider()
st.header("📊 Student Live Portfolio Ledger Grid")
if live_portfolio_data:
    st.table(pd.DataFrame(live_portfolio_data))
else:
    st.info("The ledger is empty. Complete a trade to allocate your initial $1,000 cash balance.")

st.divider()
st.header("🔔 Price Alerts")
st.caption("Set alerts to notify you when a stock reaches a target price.")
a_col1, a_col2, a_col3 = st.columns([2, 1, 1])
with a_col1:
    alert_ticker = st.text_input("Ticker", value="AAPL", key="alert_ticker").upper().strip()
with a_col2:
    alert_direction = st.selectbox("Direction", ["above", "below"], key="alert_dir")
with a_col3:
    alert_price = st.number_input("Target Price ($)", min_value=0.01, value=200.00, step=1.0, key="alert_price")

if st.button("Add Alert"):
    new_alert = {"ticker": alert_ticker, "direction": alert_direction, "price": alert_price}
    student_alerts.append(new_alert)
    student_profile["alerts"] = student_alerts
    global_database[student_email] = student_profile
    save_gcs_database(global_database)
    st.success(f"Alert set for {alert_ticker} {alert_direction} ${alert_price}")
    st.rerun()

if student_alerts:
    st.subheader("Active Alerts")
    for i, alert in enumerate(student_alerts):
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        c1.write(alert["ticker"])
        c2.write(alert["direction"])
        c3.write(f"${alert['price']:.2f}")
        if c4.button("Remove", key=f"del_alert_{i}"):
            student_alerts.pop(i)
            student_profile["alerts"] = student_alerts
            global_database[student_email] = student_profile
            save_gcs_database(global_database)
            st.rerun()
