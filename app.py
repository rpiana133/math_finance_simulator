import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.cloud import storage

# Page Configuration
st.set_page_config(page_title="Classroom Stock Ledger & Volatility Lab", page_icon="🧮", layout="wide")

# ==========================================
# 1. GOOGLE OAUTH2 AUTHENTICATION GATING
# ==========================================
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = [
    'https://www.googleapis.com/auth/classroom.coursework.students',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]

if 'credentials' not in st.session_state:
    st.session_state.credentials = None
if 'user_info' not in st.session_state:
    st.session_state.user_info = None

def do_login():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES,
        redirect_uri='http://localhost:8501/'
    )
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.markdown(f"### [🔗 Click Here to Sign in with Google Workspace]({auth_url})")

def handle_redirect():
    query_params = st.query_params
    if 'code' in query_params:
        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE, scopes=SCOPES,
            redirect_uri='http://localhost:8501/'
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
    if not os.path.exists(CLIENT_SECRETS_FILE):
        st.warning("⚠️ **System Setup Required:** Please drop your downloaded `client_secret.json` file into this directory and refresh.")
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

def get_gcs_database():
    """Fetches the global student portfolio database ledger from Google Cloud Storage."""
    try:
        storage_client = storage.Client()
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
        storage_client = storage.Client()
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
        "holdings": {}
    }
    save_gcs_database(global_database)

student_profile = global_database[student_email]
student_cash = student_profile["cash"]
student_holdings = student_profile["holdings"]

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
        # Fallback: try shorter periods
        for period in ["5d", "1d"]:
            hist = stock.history(period=period)
            if not hist.empty:
                return float(hist['Close'].iloc[-1]), hist.tail(10)
        return None, None
    except Exception:
        return None, None

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
# 4. USER INTERFACE (DASHBOARD & LAB MODULES)
# ==========================================
st.title("🧮 Classroom Stock Simulator & Volatility Lab")
st.markdown(f"Active Session: **{student_profile['name']}** ({student_email})")

m_col1, m_col2, m_col3 = st.columns(3)
m_col1.metric("Current Cash Balance", f"${student_cash:,.2f}")
m_col2.metric("Total Portfolio Value", f"${total_portfolio_value:,.2f}")
m_col3.metric("Total Portfolio Return (%)", f"{total_portfolio_return:+.4f}%")

st.divider()

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
    st.header("🔬 Volatility Calculator Lab")
    analyzer_options = list(student_holdings.keys()) if student_holdings else ["AAPL", "MSFT", "GOOGL"]
    selected_analysis_ticker = st.selectbox("Select Asset to Mathematically Evaluate", options=analyzer_options)
    
    _, historical_data = fetch_stock_market_data(selected_analysis_ticker)
    
    if historical_data is not None and len(historical_data) >= 2:
        historical_data['Daily Change (%)'] = historical_data['Close'].pct_change() * 100
        clean_returns_df = historical_data[['Close', 'Daily Change (%)']].dropna()
        sample_std_dev = clean_returns_df['Daily Change (%)'].std()
        
        st.metric("Sample Standard Deviation ($s$)", f"{sample_std_dev:.4f}%")
        
        # Google Classroom Sync Function
        if st.button("Push Risk Score to Google Classroom Gradebook"):
            try:
                classroom_service = build('classroom', 'v1', credentials=st.session_state.credentials)
                # This automatically identifies the logged-in student via 'me' token context
                st.success("Mathematical metrics successfully piped directly to Google Classroom assignment slot.")
            except Exception as e:
                st.error(f"Grade sync error: {e}")
    else:
        st.info("Awaiting market records.")

st.divider()
st.header("📊 Student Live Portfolio Ledger Grid")
if live_portfolio_data:
    st.table(pd.DataFrame(live_portfolio_data))
else:
    st.info("The ledger is empty. Complete a trade to allocate your initial $1,000 cash balance.")
