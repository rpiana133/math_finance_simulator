import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import json
import time
import urllib.parse
import requests
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request as AuthReq
from google.auth import crypt
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

# Legal Pages (rendered before login wall so unauthenticated users can view them)
LEGAL_STYLES = """
<style>
.legal-page { max-width: 720px; margin: 0 auto; }
.legal-page h2 { color: #1a237e; font-size: 1.8rem; margin-top: 2rem; }
.legal-page h3 { color: #283593; font-size: 1.3rem; margin-top: 1.5rem; }
.legal-page p, .legal-page li { color: #374151; line-height: 1.7; }
.legal-page hr { margin: 2rem 0; }
</style>
"""

def _render_privacy():
    st.markdown(LEGAL_STYLES, unsafe_allow_html=True)
    st.markdown('<div class="legal-page">', unsafe_allow_html=True)
    st.markdown("## 📈 Math Finance Simulator")
    st.markdown("### Privacy Policy")
    st.markdown("*Last updated: May 29, 2026*")
    st.markdown("**Information We Collect**")
    st.markdown("- **Google Account Information:** When you sign in with Google Workspace, we receive your name, email address, and profile picture. We use this only to identify you within the classroom simulator.")
    st.markdown("- **Portfolio Data:** Your simulated trades, holdings, cash balance, and alert settings are stored in Google Cloud Storage and associated with your email address.")
    st.markdown("**How We Use Your Information**")
    st.markdown("- To provide and maintain the stock market simulation")
    st.markdown("- To display your portfolio performance and classroom standings")
    st.markdown("- To persist your data across sessions")
    st.markdown("**Data Storage & Security**")
    st.markdown("Your data is stored in Google Cloud Storage (GCS) with encryption at rest. Access is restricted to the application service account and your classroom teacher.")
    st.markdown("**Data Retention**")
    st.markdown("Your data is retained for the duration of the course. Upon request by your teacher, your account and associated data will be deleted.")
    st.markdown("**Third-Party Services**")
    st.markdown("- **Google Workspace:** Authentication only")
    st.markdown("- **Google Cloud Storage:** Data persistence")
    st.markdown("- **Yahoo Finance (yfinance):** Real-time and historical stock price data")
    st.markdown("**Contact**")
    st.markdown("For questions about this policy, contact your classroom instructor or the system administrator at St. John's School Guam.")
    st.markdown("**Changes**")
    st.markdown("We may update this policy. Changes will be communicated through the application.")
    st.markdown('<hr>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

def _render_terms():
    st.markdown(LEGAL_STYLES, unsafe_allow_html=True)
    st.markdown('<div class="legal-page">', unsafe_allow_html=True)
    st.markdown("## 📈 Math Finance Simulator")
    st.markdown("### Terms of Service")
    st.markdown("*Last updated: May 29, 2026*")
    st.markdown("**Acceptance**")
    st.markdown("By using Math Finance Simulator, you agree to these terms. This is an educational simulation tool for classroom use only.")
    st.markdown("**Educational Purpose Only**")
    st.markdown("- This application is a **simulation** using delayed market data from Yahoo Finance.")
    st.markdown("- All trades are **fictional** — no real money is involved.")
    st.markdown("- The simulator is for educational purposes and does not constitute financial advice.")
    st.markdown("**User Responsibilities**")
    st.markdown("- Use your school-provided Google Workspace account")
    st.markdown("- Do not attempt to access other users' data")
    st.markdown("- Do not manipulate or exploit the simulation")
    st.markdown("- Follow your instructor's guidelines for classroom use")
    st.markdown("**No Real Trading**")
    st.markdown("Math Finance Simulator does not execute real stock trades, handle real money, or provide investment recommendations.")
    st.markdown("**Data Disclaimer**")
    st.markdown("Stock price data is provided by Yahoo Finance and may be delayed. We are not responsible for data inaccuracies or service interruptions.")
    st.markdown("**Limitation of Liability**")
    st.markdown('This software is provided "as is" without warranty. The developers and St. John\'s School Guam are not liable for any losses arising from its use.')
    st.markdown("**Termination**")
    st.markdown("Your instructor may revoke access at any time. Upon course completion, your account may be deactivated.")
    st.markdown("**Governing Law**")
    st.markdown("These terms are governed by the laws of Guam, United States.")
    st.markdown('<hr>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# Handle legal page routes via query params (before login wall)
if "page" not in st.session_state:
    try:
        if "page" in st.query_params:
            st.session_state.page = st.query_params["page"]
            st.rerun()
    except Exception:
        pass

if st.session_state.get("page") == "privacy":
    _render_privacy()
    if st.button("← Back to App"):
        del st.session_state.page
        st.query_params.clear()
        st.rerun()
    st.stop()
elif st.session_state.get("page") == "terms":
    _render_terms()
    if st.button("← Back to App"):
        del st.session_state.page
        st.query_params.clear()
        st.rerun()
    st.stop()

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
BLOB_PREFIX = "portfolios/"
student_email = st.session_state.user_info['email']

def _gcs_creds():
    raw = st.secrets.get("GCS_SERVICE_ACCOUNT")
    if raw:
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            pass
    # Build from individual secret fields (user has them as separate TOML keys)
    fields = {
        "type": "service_account",
        "project_id": st.secrets.get("project_id", ""),
        "private_key_id": st.secrets.get("private_key_id", ""),
        "private_key": st.secrets.get("private_key", ""),
        "client_email": st.secrets.get("client_email", ""),
        "client_id": st.secrets.get("client_id", ""),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": st.secrets.get("client_x509_cert_url", ""),
        "universe_domain": "googleapis.com"
    }
    return fields

@st.cache_resource(ttl=1500)
def _gcs_token():
    key_info = _gcs_creds()
    signer = crypt.RSASigner.from_service_account_info(key_info)
    now = int(time.time())
    jwt_payload = {
        "iss": key_info["client_email"],
        "scope": "https://www.googleapis.com/auth/devstorage.read_write",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now
    }
    from google.auth import jwt as google_jwt
    assertion = google_jwt.encode(signer, jwt_payload, key_id=key_info.get("private_key_id"))
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion
    })
    try:
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as e:
        st.error(f"OAuth2 token error: {e} | Status: {resp.status_code} | Body: {resp.text[:500]}")
        raise

def _gcs_read(path):
    token = _gcs_token()
    resp = requests.get(f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text

def _gcs_write(path, data):
    token = _gcs_token()
    resp = requests.put(f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        data=data.encode('utf-8'), headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
    resp.raise_for_status()

def _gcs_exists(path):
    token = _gcs_token()
    resp = requests.get(f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        headers={"Authorization": f"Bearer {token}"})
    return resp.status_code == 200

def _gcs_list(prefix):
    token = _gcs_token()
    resp = requests.get(
        f"https://storage.googleapis.com/storage/v1/b/{GCS_BUCKET_NAME}/o?prefix={urllib.parse.quote(prefix)}",
        headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [item["name"] for item in data.get("items", [])]

def get_gcs_client():
    key_info = json.loads(st.secrets["GCS_SERVICE_ACCOUNT"])
    creds = service_account.Credentials.from_service_account_info(key_info)
    client = storage.Client(credentials=creds, project=key_info.get("project_id"))
    return client

def load_student_profile(email):
    try:
        data = _gcs_read(f"{BLOB_PREFIX}{email}.json")
        if data is None:
            # Fallback: check without prefix
            data = _gcs_read(f"{email}.json")
            if data is not None:
                profile = json.loads(data)
                save_student_profile(email, profile)
                return profile
            return None
        return json.loads(data)
    except Exception as e:
        st.error(f"GCS load error: {e}")
        if 'profiles_cache' not in st.session_state:
            st.session_state.profiles_cache = {}
        return st.session_state.profiles_cache.get(email)

def save_student_profile(email, profile):
    try:
        payload = json.dumps(profile, indent=4)
    except Exception as e:
        st.error(f"JSON serialization error: {e}")
        return
    try:
        _gcs_write(f"{BLOB_PREFIX}{email}.json", payload)
    except Exception as e:
        st.error(f"GCS save error: {e}")
        if 'profiles_cache' not in st.session_state:
            st.session_state.profiles_cache = {}
        st.session_state.profiles_cache[email] = profile

config_teacher_email = "rpiana@stjohnsguam.com"

def get_gcs_database():
    """Fetch all student portfolios from GCS by listing per-student files."""
    names = _gcs_list(BLOB_PREFIX)
    db = {}
    for name in names:
        email = name[len(BLOB_PREFIX):-5]  # strip prefix + .json
        data = _gcs_read(name)
        if data:
            db[email] = json.loads(data)
    return db

# Load this student's profile
student_profile = load_student_profile(student_email)
if student_profile is None:
    # Migration: try reading from the old monolithic file
    try:
        old_json = _gcs_read("classroom_portfolios.json")
        if old_json:
            old_data = json.loads(old_json)
            if student_email in old_data:
                student_profile = old_data[student_email]
                student_profile.setdefault("unsettled_cash", 0.0)
                student_profile.setdefault("unsettled_entries", [])
                save_student_profile(student_email, student_profile)
    except Exception:
        pass

if student_profile is None:
    student_profile = {
        "name": st.session_state.user_info.get('name', 'Student'),
        "cash": 1000.00,
        "holdings": {},
        "alerts": [],
        "history": [],
        "unsettled_cash": 0.0,
        "unsettled_entries": [],
        "dividend_tracker": {},
        "total_dividends_earned": 0.0
    }
    save_student_profile(student_email, student_profile)

# Settle any unsettled proceeds older than 24 hours
student_profile.setdefault("total_dividends_earned", 0.0)
now = datetime.now()
unsettled_entries = student_profile.get("unsettled_entries", [])
settled_amount = 0.0
remaining = []
for entry in unsettled_entries:
    if (now - datetime.fromisoformat(entry["time"])).total_seconds() >= 86400:
        settled_amount += entry["amount"]
    else:
        remaining.append(entry)
if settled_amount > 0:
    student_profile["cash"] = round(student_profile["cash"] + settled_amount, 2)
    student_profile["unsettled_entries"] = remaining
    student_profile["unsettled_cash"] = round(sum(e["amount"] for e in remaining), 2)
    save_student_profile(student_email, student_profile)

student_cash = student_profile["cash"]
student_unsettled = student_profile.get("unsettled_cash", 0.0)
student_holdings = student_profile["holdings"]
student_alerts = student_profile.get("alerts", [])
student_history = student_profile.get("history", [])

# Weekly $100 deposit
now = datetime.now()
total_deposits = student_profile.get("total_deposits", 0.0)
last_deposit_str = student_profile.get("last_weekly_deposit")
if last_deposit_str:
    last_deposit = datetime.fromisoformat(last_deposit_str)
    weeks_passed = int((now - last_deposit).days / 7)
    if weeks_passed >= 1:
        deposit_amount = weeks_passed * 100
        student_profile["cash"] = round(student_cash + deposit_amount, 2)
        student_profile["total_deposits"] = round(total_deposits + deposit_amount, 2)
        student_profile["last_weekly_deposit"] = now.isoformat()
        save_student_profile(student_email, student_profile)
        st.success(f"💰 Weekly deposit: +${deposit_amount:.2f} ({weeks_passed} week{'s' if weeks_passed > 1 else ''})")
else:
    student_profile["last_weekly_deposit"] = now.isoformat()
    save_student_profile(student_email, student_profile)

# Dividend auto-credit
@st.cache_data(ttl=86400)
def get_dividends(ticker):
    try:
        t = yf.Ticker(ticker)
        divs = t.dividends
        if divs is None or divs.empty:
            return None
        return divs
    except Exception:
        return None

dividend_tracker = student_profile.setdefault("dividend_tracker", {})
total_dividends = 0.0
for ticker, position in list(student_holdings.items()):
    last_date_str = dividend_tracker.get(ticker)
    divs = get_dividends(ticker)
    if divs is None or divs.empty:
        continue
    latest_div_date = divs.index[-1]
    latest_div_amount = float(divs.iloc[-1])
    if last_date_str is None:
        dividend_tracker[ticker] = latest_div_date.isoformat()
        continue
    if latest_div_date > datetime.fromisoformat(last_date_str):
        amount = position['shares'] * latest_div_amount
        if amount > 0:
            student_profile["cash"] = round(student_profile["cash"] + amount, 2)
            student_profile["total_dividends_earned"] = round(
                student_profile.get("total_dividends_earned", 0.0) + amount, 2)
            student_profile.setdefault("history", []).append({
                "type": "dividend", "ticker": ticker,
                "shares": round(position['shares'], 4),
                "dividend_per_share": round(latest_div_amount, 4),
                "total": round(amount, 2),
                "time": datetime.now().isoformat()
            })
            total_dividends += amount
        dividend_tracker[ticker] = latest_div_date.isoformat()
if total_dividends > 0:
    st.success(f"💰 ${total_dividends:.2f} in dividends collected!")
    save_student_profile(student_email, student_profile)

# Refresh local variables after potential deposit
student_cash = student_profile["cash"]

# ==========================================
# 3. STOCK DATA & REAL-TIME MATHEMATICS ENGINE
# ==========================================
POPULAR_STOCKS = {
    "MMM": "3M",
    "AOS": "A. O. Smith",
    "ABT": "Abbott Laboratories",
    "ABBV": "AbbVie",
    "ACN": "Accenture",
    "ADBE": "Adobe Inc.",
    "AMD": "Advanced Micro Devices",
    "AES": "AES Corporation",
    "AFL": "Aflac",
    "A": "Agilent Technologies",
    "APD": "Air Products",
    "ABNB": "Airbnb",
    "AKAM": "Akamai Technologies",
    "ALB": "Albemarle Corporation",
    "ARE": "Alexandria Real Estate Equities",
    "ARM": "Arm Holdings",
    "ALGN": "Align Technology",
    "ALLE": "Allegion",
    "LNT": "Alliant Energy",
    "ALL": "Allstate",
    "GOOGL": "Alphabet Inc. (Class A)",
    "GOOG": "Alphabet Inc. (Class C)",
    "MO": "Altria",
    "AMZN": "Amazon",
    "AMCR": "Amcor",
    "AEE": "Ameren",
    "AEP": "American Electric Power",
    "AXP": "American Express",
    "AIG": "American International Group",
    "AMT": "American Tower",
    "AWK": "American Water Works",
    "AMP": "Ameriprise Financial",
    "AME": "Ametek",
    "AMGN": "Amgen",
    "APH": "Amphenol",
    "ADI": "Analog Devices",
    "AON": "Aon plc",
    "APA": "APA Corporation",
    "APO": "Apollo Global Management",
    "AAPL": "Apple Inc.",
    "AMAT": "Applied Materials",
    "APP": "AppLovin",
    "APTV": "Aptiv",
    "ACGL": "Arch Capital Group",
    "ADM": "Archer Daniels Midland",
    "ARES": "Ares Management",
    "ANET": "Arista Networks",
    "AJG": "Arthur J. Gallagher & Co.",
    "AIZ": "Assurant",
    "T": "AT&T",
    "ATO": "Atmos Energy",
    "ADSK": "Autodesk",
    "ADP": "Automatic Data Processing",
    "AZO": "AutoZone",
    "AVB": "AvalonBay Communities",
    "AVY": "Avery Dennison",
    "AXON": "Axon Enterprise",
    "BKR": "Baker Hughes",
    "BALL": "Ball Corporation",
    "BAC": "Bank of America",
    "BAX": "Baxter International",
    "BDX": "Becton Dickinson",
    "BRK.B": "Berkshire Hathaway",
    "BBY": "Best Buy",
    "TECH": "Bio-Techne",
    "BIIB": "Biogen",
    "BLK": "BlackRock",
    "BX": "Blackstone Inc.",
    "XYZ": "Block, Inc.",
    "BNY": "BNY Mellon",
    "BA": "Boeing",
    "BKNG": "Booking Holdings",
    "BSX": "Boston Scientific",
    "BMY": "Bristol Myers Squibb",
    "AVGO": "Broadcom",
    "BR": "Broadridge Financial Solutions",
    "BRO": "Brown & Brown",
    "BF.B": "Brown–Forman",
    "BLDR": "Builders FirstSource",
    "BG": "Bunge Global",
    "BXP": "BXP, Inc.",
    "CHRW": "C.H. Robinson",
    "CDNS": "Cadence Design Systems",
    "CPT": "Camden Property Trust",
    "CPB": "Campbell's Company (The)",
    "COF": "Capital One",
    "CAH": "Cardinal Health",
    "CCL": "Carnival Corporation",
    "CARR": "Carrier Global",
    "CVNA": "Carvana",
    "CASY": "Casey's",
    "CAT": "Caterpillar Inc.",
    "CBOE": "Cboe Global Markets",
    "CBRE": "CBRE Group",
    "CDW": "CDW Corporation",
    "COR": "Cencora",
    "CNC": "Centene Corporation",
    "CNP": "CenterPoint Energy",
    "CF": "CF Industries",
    "CRL": "Charles River Laboratories",
    "SCHW": "Charles Schwab Corporation",
    "CHTR": "Charter Communications",
    "CVX": "Chevron Corporation",
    "CMG": "Chipotle Mexican Grill",
    "CB": "Chubb Limited",
    "CHD": "Church & Dwight",
    "CIEN": "Ciena",
    "CI": "Cigna",
    "CINF": "Cincinnati Financial",
    "CTAS": "Cintas",
    "CSCO": "Cisco",
    "C": "Citigroup",
    "CFG": "Citizens Financial Group",
    "CLX": "Clorox",
    "CME": "CME Group",
    "CMS": "CMS Energy",
    "KO": "Coca-Cola Company (The)",
    "CTSH": "Cognizant",
    "COHR": "Coherent Corp.",
    "COIN": "Coinbase",
    "CL": "Colgate-Palmolive",
    "CMCSA": "Comcast",
    "FIX": "Comfort Systems USA",
    "CAG": "Conagra Brands",
    "COP": "ConocoPhillips",
    "ED": "Consolidated Edison",
    "STZ": "Constellation Brands",
    "CEG": "Constellation Energy",
    "COO": "Cooper Companies (The)",
    "CPRT": "Copart",
    "GLW": "Corning Inc.",
    "CPAY": "Corpay",
    "CTVA": "Corteva",
    "CSGP": "CoStar Group",
    "COST": "Costco",
    "CRH": "CRH plc",
    "CRWD": "CrowdStrike",
    "CCI": "Crown Castle",
    "CSX": "CSX Corporation",
    "CMI": "Cummins",
    "CVS": "CVS Health",
    "DHR": "Danaher Corporation",
    "DRI": "Darden Restaurants",
    "DDOG": "Datadog",
    "DVA": "DaVita",
    "DECK": "Deckers Brands",
    "DE": "Deere & Company",
    "DELL": "Dell Technologies",
    "DAL": "Delta Air Lines",
    "DVN": "Devon Energy",
    "DXCM": "Dexcom",
    "FANG": "Diamondback Energy",
    "DLR": "Digital Realty",
    "DG": "Dollar General",
    "DLTR": "Dollar Tree",
    "D": "Dominion Energy",
    "DPZ": "Domino's",
    "DASH": "DoorDash",
    "DOV": "Dover Corporation",
    "DOW": "Dow Inc.",
    "DHI": "D. R. Horton",
    "DTE": "DTE Energy",
    "DUK": "Duke Energy",
    "DD": "DuPont",
    "ETN": "Eaton Corporation",
    "EBAY": "eBay Inc.",
    "SATS": "EchoStar",
    "ECL": "Ecolab",
    "EIX": "Edison International",
    "EW": "Edwards Lifesciences",
    "EA": "Electronic Arts",
    "ELV": "Elevance Health",
    "EME": "Emcor",
    "EMR": "Emerson Electric",
    "ETR": "Entergy",
    "EOG": "EOG Resources",
    "EPAM": "EPAM Systems",
    "EQT": "EQT Corporation",
    "EFX": "Equifax",
    "EQIX": "Equinix",
    "EQR": "Equity Residential",
    "ERIE": "Erie Indemnity",
    "ESS": "Essex Property Trust",
    "EL": "Estée Lauder Companies (The)",
    "EG": "Everest Group",
    "EVRG": "Evergy",
    "ES": "Eversource Energy",
    "EXC": "Exelon",
    "EXE": "Expand Energy",
    "EXPE": "Expedia Group",
    "EXPD": "Expeditors International",
    "EXR": "Extra Space Storage",
    "XOM": "ExxonMobil",
    "FFIV": "F5, Inc.",
    "FDS": "FactSet",
    "FICO": "Fair Isaac",
    "FAST": "Fastenal",
    "FRT": "Federal Realty Investment Trust",
    "FDX": "FedEx",
    "FIS": "Fidelity National Information Services",
    "FITB": "Fifth Third Bancorp",
    "FSLR": "First Solar",
    "FE": "FirstEnergy",
    "FISV": "Fiserv",
    "F": "Ford Motor Company",
    "FTNT": "Fortinet",
    "FTV": "Fortive",
    "FOXA": "Fox Corporation (Class A)",
    "FOX": "Fox Corporation (Class B)",
    "BEN": "Franklin Resources",
    "FCX": "Freeport-McMoRan",
    "GRMN": "Garmin",
    "IT": "Gartner",
    "GE": "GE Aerospace",
    "GEHC": "GE HealthCare",
    "GEV": "GE Vernova",
    "GEN": "Gen Digital",
    "GNRC": "Generac",
    "GD": "General Dynamics",
    "GIS": "General Mills",
    "GM": "General Motors",
    "GPC": "Genuine Parts Company",
    "GILD": "Gilead Sciences",
    "GPN": "Global Payments",
    "GL": "Globe Life",
    "GDDY": "GoDaddy",
    "GS": "Goldman Sachs",
    "HAL": "Halliburton",
    "HIG": "Hartford (The)",
    "HAS": "Hasbro",
    "HCA": "HCA Healthcare",
    "DOC": "Healthpeak Properties",
    "HSIC": "Henry Schein",
    "HSY": "Hershey Company (The)",
    "HPE": "Hewlett Packard Enterprise",
    "HLT": "Hilton Worldwide",
    "HD": "Home Depot (The)",
    "HON": "Honeywell",
    "HRL": "Hormel Foods",
    "HST": "Host Hotels & Resorts",
    "HWM": "Howmet Aerospace",
    "HPQ": "HP Inc.",
    "HUBB": "Hubbell Incorporated",
    "HUM": "Humana",
    "HBAN": "Huntington Bancshares",
    "HII": "Huntington Ingalls Industries",
    "IBM": "IBM",
    "IEX": "IDEX Corporation",
    "IDXX": "Idexx Laboratories",
    "ITW": "Illinois Tool Works",
    "INCY": "Incyte",
    "IR": "Ingersoll Rand",
    "PODD": "Insulet Corporation",
    "INTC": "Intel",
    "IBKR": "Interactive Brokers",
    "ICE": "Intercontinental Exchange",
    "IFF": "International Flavors & Fragrances",
    "IP": "International Paper",
    "INTU": "Intuit",
    "ISRG": "Intuitive Surgical",
    "IVZ": "Invesco",
    "INVH": "Invitation Homes",
    "IQV": "IQVIA",
    "IRM": "Iron Mountain",
    "JBHT": "J.B. Hunt",
    "JBL": "Jabil",
    "JKHY": "Jack Henry & Associates",
    "J": "Jacobs Solutions",
    "JNJ": "Johnson & Johnson",
    "JCI": "Johnson Controls",
    "JPM": "JPMorgan Chase",
    "KVUE": "Kenvue",
    "KDP": "Keurig Dr Pepper",
    "KEY": "KeyCorp",
    "KEYS": "Keysight Technologies",
    "KMB": "Kimberly-Clark",
    "KIM": "Kimco Realty",
    "KMI": "Kinder Morgan",
    "KKR": "KKR & Co.",
    "KLAC": "KLA Corporation",
    "KHC": "Kraft Heinz",
    "KR": "Kroger",
    "LHX": "L3Harris",
    "LH": "Labcorp",
    "LRCX": "Lam Research",
    "LVS": "Las Vegas Sands",
    "LDOS": "Leidos",
    "LEN": "Lennar",
    "LII": "Lennox International",
    "LLY": "Lilly (Eli)",
    "LIN": "Linde plc",
    "LYV": "Live Nation Entertainment",
    "LMT": "Lockheed Martin",
    "L": "Loews Corporation",
    "LOW": "Lowe's",
    "LULU": "Lululemon Athletica",
    "LITE": "Lumentum",
    "LYB": "LyondellBasell",
    "MTB": "M&T Bank",
    "MPC": "Marathon Petroleum",
    "MAR": "Marriott International",
    "MRSH": "Marsh McLennan",
    "MLM": "Martin Marietta Materials",
    "MAS": "Masco",
    "MA": "Mastercard",
    "MKC": "McCormick & Company",
    "MCD": "McDonald's",
    "MCK": "McKesson Corporation",
    "MDT": "Medtronic",
    "MRK": "Merck & Co.",
    "META": "Meta Platforms",
    "MET": "MetLife",
    "MTD": "Mettler Toledo",
    "MGM": "MGM Resorts",
    "MCHP": "Microchip Technology",
    "MU": "Micron Technology",
    "MSFT": "Microsoft",
    "MAA": "Mid-America Apartment Communities",
    "MRNA": "Moderna",
    "TAP": "Molson Coors Beverage Company",
    "MDLZ": "Mondelez International",
    "MPWR": "Monolithic Power Systems",
    "MNST": "Monster Beverage",
    "MCO": "Moody's Corporation",
    "MS": "Morgan Stanley",
    "MOS": "Mosaic Company (The)",
    "MSI": "Motorola Solutions",
    "MSCI": "MSCI Inc.",
    "NDAQ": "Nasdaq, Inc.",
    "NTAP": "NetApp",
    "NFLX": "Netflix",
    "NEM": "Newmont",
    "NWSA": "News Corp (Class A)",
    "NWS": "News Corp (Class B)",
    "NEE": "NextEra Energy",
    "NKE": "Nike, Inc.",
    "NI": "NiSource",
    "NDSN": "Nordson Corporation",
    "NSC": "Norfolk Southern",
    "NTRS": "Northern Trust",
    "NOC": "Northrop Grumman",
    "NCLH": "Norwegian Cruise Line Holdings",
    "NRG": "NRG Energy",
    "NUE": "Nucor",
    "NVDA": "Nvidia",
    "NVR": "NVR, Inc.",
    "NXPI": "NXP Semiconductors",
    "ORLY": "O'Reilly Automotive",
    "OXY": "Occidental Petroleum",
    "ODFL": "Old Dominion",
    "OMC": "Omnicom Group",
    "ON": "ON Semiconductor",
    "OKE": "Oneok",
    "ORCL": "Oracle Corporation",
    "OTIS": "Otis Worldwide",
    "PCAR": "Paccar",
    "PKG": "Packaging Corporation of America",
    "PLTR": "Palantir Technologies",
    "PANW": "Palo Alto Networks",
    "PSKY": "Paramount Skydance Corporation",
    "PH": "Parker Hannifin",
    "PAYX": "Paychex",
    "PYPL": "PayPal",
    "PNR": "Pentair",
    "PEP": "PepsiCo",
    "PFE": "Pfizer",
    "PCG": "PG&E Corporation",
    "PM": "Philip Morris International",
    "PSX": "Phillips 66",
    "PNW": "Pinnacle West Capital",
    "PNC": "PNC Financial Services",
    "POOL": "Pool Corporation",
    "PPG": "PPG Industries",
    "PPL": "PPL Corporation",
    "PFG": "Principal Financial Group",
    "PG": "Procter & Gamble",
    "PGR": "Progressive Corporation",
    "PLD": "Prologis",
    "PRU": "Prudential Financial",
    "PEG": "Public Service Enterprise Group",
    "PTC": "PTC Inc.",
    "PSA": "Public Storage",
    "PHM": "PulteGroup",
    "PWR": "Quanta Services",
    "QCOM": "Qualcomm",
    "DGX": "Quest Diagnostics",
    "Q": "Qnity Electronics",
    "RL": "Ralph Lauren Corporation",
    "RJF": "Raymond James Financial",
    "RTX": "RTX Corporation",
    "O": "Realty Income",
    "REG": "Regency Centers",
    "REGN": "Regeneron Pharmaceuticals",
    "RF": "Regions Financial Corporation",
    "RSG": "Republic Services",
    "RMD": "ResMed",
    "RVTY": "Revvity",
    "HOOD": "Robinhood Markets",
    "ROK": "Rockwell Automation",
    "ROL": "Rollins, Inc.",
    "ROP": "Roper Technologies",
    "ROST": "Ross Stores",
    "RCL": "Royal Caribbean Group",
    "SPGI": "S&P Global",
    "CRM": "Salesforce",
    "SNDK": "Sandisk",
    "SBAC": "SBA Communications",
    "SLB": "Schlumberger",
    "STX": "Seagate Technology",
    "SRE": "Sempra",
    "NOW": "ServiceNow",
    "SHW": "Sherwin-Williams",
    "SPG": "Simon Property Group",
    "SWKS": "Skyworks Solutions",
    "SJM": "J.M. Smucker Company (The)",
    "SW": "Smurfit Westrock",
    "SNA": "Snap-on",
    "SOLV": "Solventum",
    "SO": "Southern Company",
    "LUV": "Southwest Airlines",
    "SWK": "Stanley Black & Decker",
    "SBUX": "Starbucks",
    "STT": "State Street Corporation",
    "STLD": "Steel Dynamics",
    "STE": "Steris",
    "SYK": "Stryker Corporation",
    "SMCI": "Supermicro",
    "SYF": "Synchrony Financial",
    "SNPS": "Synopsys",
    "SYY": "Sysco",
    "TMUS": "T-Mobile US",
    "TROW": "T. Rowe Price",
    "TTWO": "Take-Two Interactive",
    "TPR": "Tapestry, Inc.",
    "TRGP": "Targa Resources",
    "TGT": "Target Corporation",
    "TEL": "TE Connectivity",
    "TDY": "Teledyne Technologies",
    "TER": "Teradyne",
    "TSLA": "Tesla, Inc.",
    "TXN": "Texas Instruments",
    "TPL": "Texas Pacific Land Corporation",
    "TXT": "Textron",
    "TMO": "Thermo Fisher Scientific",
    "TJX": "TJX Companies",
    "TKO": "TKO Group Holdings",
    "TTD": "Trade Desk (The)",
    "TSCO": "Tractor Supply",
    "TT": "Trane Technologies",
    "TDG": "TransDigm Group",
    "TRV": "Travelers Companies (The)",
    "TRMB": "Trimble Inc.",
    "TFC": "Truist Financial",
    "TYL": "Tyler Technologies",
    "TSN": "Tyson Foods",
    "USB": "U.S. Bancorp",
    "UBER": "Uber",
    "UDR": "UDR, Inc.",
    "ULTA": "Ulta Beauty",
    "UNP": "Union Pacific Corporation",
    "UAL": "United Airlines Holdings",
    "UPS": "United Parcel Service",
    "URI": "United Rentals",
    "UNH": "UnitedHealth Group",
    "UHS": "Universal Health Services",
    "VLO": "Valero Energy",
    "VEEV": "Veeva Systems",
    "VTR": "Ventas",
    "VLTO": "Veralto",
    "VRSN": "Verisign",
    "VRSK": "Verisk Analytics",
    "VZ": "Verizon",
    "VRTX": "Vertex Pharmaceuticals",
    "VRT": "Vertiv",
    "VTRS": "Viatris",
    "VICI": "Vici Properties",
    "V": "Visa Inc.",
    "VST": "Vistra Corp.",
    "VMC": "Vulcan Materials Company",
    "WRB": "W. R. Berkley Corporation",
    "GWW": "W. W. Grainger",
    "WAB": "Wabtec",
    "WMT": "Walmart",
    "DIS": "Walt Disney Company (The)",
    "WBD": "Warner Bros. Discovery",
    "WM": "Waste Management",
    "WAT": "Waters Corporation",
    "WEC": "WEC Energy Group",
    "WFC": "Wells Fargo",
    "WELL": "Welltower",
    "WST": "West Pharmaceutical Services",
    "WDC": "Western Digital",
    "WY": "Weyerhaeuser",
    "WSM": "Williams-Sonoma, Inc.",
    "WMB": "Williams Companies",
    "WTW": "Willis Towers Watson",
    "WDAY": "Workday, Inc.",
    "WYNN": "Wynn Resorts",
    "XEL": "Xcel Energy",
    "XYL": "Xylem Inc.",
    "YUM": "Yum! Brands",
    "ZBRA": "Zebra Technologies",
    "ZBH": "Zimmer Biomet",
    "ZTS": "Zoetis",
    # Non-S&P 500 stocks
    "AFRM": "Affirm Holdings",
    "AMC": "AMC Entertainment",
    "CELH": "Celsius Holdings",
    "CHWY": "Chewy",
    "DKNG": "DraftKings",
    "DUOL": "Duolingo",
    "GME": "GameStop",
    "LCID": "Lucid Motors",
    "ONON": "On Holding",
    "PINS": "Pinterest",
    "RBLX": "Roblox",
    "RDDT": "Reddit",
    "RIVN": "Rivian Automotive",
    "RKLB": "Rocket Lab",
    "SNAP": "Snap Inc.",
    "SOFI": "SoFi Technologies",
    "SPOT": "Spotify Technology",
    "SQ": "Block, Inc.",
    # International ADRs
    "ADDYY": "Adidas ADR",
    "ASML": "ASML Holding",
    "AZN": "AstraZeneca ADR",
    "BABA": "Alibaba Group ADR",
    "BP": "BP ADR",
    "DEO": "Diageo ADR",
    "FRCOY": "Fast Retailing / Uniqlo ADR",
    "NIO": "NIO Inc. ADR",
    "NVS": "Novartis ADR",
    "PDD": "Pinduoduo ADR",
    "SE": "Sea Limited ADR",
    "SONY": "Sony Group ADR",
    "TM": "Toyota Motor ADR",
    "TSM": "TSMC ADR",
    "UA": "Under Armour (Class C)",
    "UAA": "Under Armour (Class A)",
    "UL": "Unilever ADR",
    # ETFs
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
    "PSI": "Invesco Dynamic Semiconductors ETF",
    # International / Country ETFs
    "FLTW": "Franklin FTSE Taiwan ETF",
    "VWO": "Vanguard FTSE Emerging Markets ETF",
    "VEA": "Vanguard FTSE Developed Markets ETF",
    "EFA": "iShares MSCI EAFE ETF",
    "IEMG": "iShares Core MSCI Emerging Markets ETF",
    "FXI": "iShares China Large-Cap ETF",
    "EWJ": "iShares MSCI Japan ETF",
    "EWG": "iShares MSCI Germany ETF",
    "EWZ": "iShares MSCI Brazil ETF",
    "INDA": "iShares MSCI India ETF",
    "KWEB": "KraneShares CSI China Internet ETF",
    "ARKK": "ARK Innovation ETF",
    "TAN": "Invesco Solar ETF",
    "ICLN": "iShares Global Clean Energy ETF",
    "XLI": "Industrial Sector ETF",
    "XLY": "Consumer Discretionary ETF",
    "XLP": "Consumer Staples ETF",
    "XLU": "Utilities Sector ETF",
    "XLB": "Materials Sector ETF",
    "XLRE": "Real Estate Sector ETF",
    # Additional ETFs
    "AGG": "Core US Aggregate Bond ETF",
    "FBTC": "Fidelity Wise Origin Bitcoin ETF",
    "HYG": "High Yield Corporate Bond ETF",
    "IBIT": "iShares Bitcoin Trust ETF",
    "IEF": "7-10 Year Treasury Bond ETF",
    "JEPI": "JPMorgan Equity Premium Income ETF",
    "JEPQ": "JPMorgan Nasdaq Premium Income ETF",
    "SHY": "1-3 Year Treasury Bond ETF",
    "TLT": "20+ Year Treasury Bond ETF",
    "VNQ": "Vanguard Real Estate ETF",
    "VT": "Total World Stock ETF",
    "VXUS": "Total International Stock ETF"
}

ALL_TICKERS = sorted(POPULAR_STOCKS.keys())

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
PICKER_PLACEHOLDER = "——— Select a ticker ———"

def stock_picker(key):
    selected = st.selectbox("Symbol", options=[PICKER_PLACEHOLDER] + DISPLAY_OPTIONS, key=key, label_visibility="collapsed")
    ticker = parse_ticker_option(selected)
    return ticker if selected != PICKER_PLACEHOLDER else None

CHART_PERIODS = {
    "1d": "1 Day", "5d": "5 Days", "1mo": "1 Month", "3mo": "3 Months",
    "6mo": "6 Months", "1y": "1 Year", "5y": "5 Years", "max": "Max"
}

def _flatten_cols(df):
    if df is not None and isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

@st.cache_data(ttl=600)
def fetch_stock_market_data(ticker):
    try:
        data = _flatten_cols(yf.download(ticker, period="1y", progress=False))
        if data.empty:
            data = _flatten_cols(yf.download(ticker, period="6mo", progress=False))
        if data.empty:
            data = _flatten_cols(yf.download(ticker, period="1mo", progress=False))
        if data.empty:
            return None, None, None
        close_price = float(data['Close'].squeeze().iloc[-1])
        try:
            info = yf.Ticker(ticker).info
            company_name = info.get('shortName') or info.get('longName') or ticker
        except Exception:
            company_name = ticker
        recent = data.tail(10) if len(data) >= 10 else data
        return close_price, recent, company_name
    except Exception:
        return None, None, None

@st.cache_data(ttl=600)
def fetch_full_history(ticker, period="3mo"):
    try:
        data = _flatten_cols(yf.download(ticker, period=period, progress=False))
        if data.empty:
            return None
        return data
    except Exception:
        return None

total_holding_value = 0.0
total_cost_basis = 0.0
live_portfolio_data = []

for ticker, position in list(student_holdings.items()):
    live_price, _, _ = fetch_stock_market_data(ticker)
    if live_price is not None:
        current_val = position['shares'] * live_price
        total_holding_value += current_val
        total_cost_basis += position['total_cost']
        avg_purchase_price = position['total_cost'] / position['shares']
        pct_return = ((live_price - avg_purchase_price) / avg_purchase_price) * 100
        
        live_portfolio_data.append({
            "Ticker": ticker,
            "Shares": round(position['shares'], 4),
            "Avg Purchase Price": f"${avg_purchase_price:.2f}",
            "Live Price": f"${live_price:.2f}",
            "Total Value": f"${current_val:.2f}",
            "Return": pct_return
        })

total_portfolio_value = student_cash + student_unsettled + total_holding_value
total_capital = 1000.00 + student_profile.get("total_deposits", 0.0)
total_pl_dollars = total_portfolio_value - total_capital
total_pl_pct = ((total_portfolio_value - total_capital) / total_capital) * 100 if total_capital else 0.0
stock_pl_dollars = total_holding_value - total_cost_basis
stock_pl_pct = (stock_pl_dollars / total_cost_basis) * 100 if total_cost_basis else 0.0
pl_class = "positive" if stock_pl_dollars >= 0 else "negative"

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

    sma20 = hist['Close'].rolling(20).mean()
    sma50 = hist['Close'].rolling(50).mean()
    vol_sma20 = hist['Volume'].rolling(20).mean()

    volume_colors = ['#16a34a' if hist['Close'].iloc[i] >= hist['Open'].iloc[i] else '#dc2626' for i in range(len(hist))]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.8, 0.2]
    )
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist['Open'], high=hist['High'],
        low=hist['Low'], close=hist['Close'], name=ticker,
        increasing_line_color='#16a34a', decreasing_line_color='#dc2626',
        line=dict(width=1)
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=hist.index, y=sma20, name='SMA 20',
        line=dict(color='#6366f1', width=1.2, dash='dash')
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=hist.index, y=sma50, name='SMA 50',
        line=dict(color='#f59e0b', width=1.5)
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=hist.index, y=hist['Volume'], name='Volume',
        marker_color=volume_colors, showlegend=False, opacity=0.8
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=hist.index, y=vol_sma20, name='Vol SMA 20',
        line=dict(color='#a855f7', width=1, dash='dot'), showlegend=False
    ), row=2, col=1)
    fig.update_layout(
        title=f"{ticker}{period_text}",
        height=500, margin=dict(l=0, r=0, t=35, b=0),
        template="none",
        hovermode="x unified",
        font=dict(family="Inter, -apple-system, sans-serif", size=11),
        paper_bgcolor='white', plot_bgcolor='white',
        legend=dict(orientation="h", y=1.12, x=0, xanchor="left", font=dict(size=10)),
    )
    fig.update_xaxes(
        title_text="Date", rangeslider_visible=False,
        gridcolor='#f0f2f5', zerolinecolor='#e5e7eb',
        tickformat="%b %d, %Y",
        rangeselector=dict(
            buttons=list([
                dict(count=1, label="1m", step="month", stepmode="backward"),
                dict(count=3, label="3m", step="month", stepmode="backward"),
                dict(count=6, label="6m", step="month", stepmode="backward"),
                dict(count=1, label="YTD", step="year", stepmode="todate"),
                dict(count=1, label="1y", step="year", stepmode="backward"),
                dict(step="all", label="Max")
            ]),
            bgcolor='white', activecolor='#e8eaff',
        )
    )
    fig.update_yaxes(
        title_text="Price ($)", gridcolor='#f0f2f5', zerolinecolor='#e5e7eb',
        tickprefix="$", side='right'
    )
    fig.update_yaxes(
        title_text="Volume", gridcolor='#f0f2f5', zerolinecolor='#e5e7eb',
        row=2, col=1, tickformat=".2s", side='right'
    )
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
        <div class="label">Unsettled Cash</div>
        <div class="value" style="color:#f59e0b;">${student_unsettled:,.2f}</div>
        <div class="sub" style="color:#9ca3af;">settles in &lt;24h</div>
    </div>
    <div class="item">
        <div class="label">Portfolio Value</div>
        <div class="value">${total_holding_value:,.2f}</div>
        <div class="sub {pl_class}">{"+" if stock_pl_dollars >= 0 else ""}${stock_pl_dollars:,.2f} ({stock_pl_pct:+.2f}%)</div>
    </div>
    <div class="item">
        <div class="label">Dividends Earned</div>
        <div class="value" style="color:#059669;">${student_profile.get("total_dividends_earned", 0.0):,.2f}</div>
    </div>
    <div class="item">
        <div class="label">Total Account</div>
        <div class="value">${total_portfolio_value:,.2f}</div>
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
    # Build allocation chart data
    labels = []
    values = []
    colors = []
    if student_cash > 0:
        labels.append("Cash")
        values.append(student_cash)
        colors.append("#6366f1")
    if student_unsettled > 0:
        labels.append("Unsettled")
        values.append(student_unsettled)
        colors.append("#f59e0b")
    # Group holdings into US vs International
    international_tickers = {"VWO", "VEA", "EFA", "IEMG", "FXI", "EWJ", "EWG", "EWZ",
                            "INDA", "KWEB", "EEM", "FLTW", "TAN", "ICLN"}
    us_value = 0.0
    intl_value = 0.0
    for ticker, pos in student_holdings.items():
        price, _, _ = fetch_stock_market_data(ticker)
        if price is not None:
            mv = pos['shares'] * price
            if ticker.upper() in international_tickers:
                intl_value += mv
            else:
                us_value += mv
    if us_value > 0:
        labels.append("US")
        values.append(us_value)
        colors.append("#22c55e")
    if intl_value > 0:
        labels.append("International")
        values.append(intl_value)
        colors.append("#3b82f6")
    # Donut charts side by side
    stock_labels = []
    stock_values = []
    stock_colors = []
    palette = ["#6366f1", "#f59e0b", "#22c55e", "#3b82f6", "#ef4444", "#8b5cf6",
               "#ec4899", "#14b8a6", "#f97316", "#06b6d4"]
    for i, ticker in enumerate(student_holdings):
        price, _, _ = fetch_stock_market_data(ticker)
        if price is not None:
            sv = student_holdings[ticker]['shares'] * price
            stock_labels.append(ticker)
            stock_values.append(sv)
            stock_colors.append(palette[i % len(palette)])
    if values or stock_values:
        cols = st.columns(2)
    if values:
        with cols[0]:
            fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.4,
                                          marker=dict(colors=colors, line=dict(color='#fff', width=2)),
                                          textinfo='label+percent', textposition='outside',
                                          textfont=dict(size=11))])
            fig.update_layout(height=280, margin=dict(l=0, r=0, t=0, b=0),
                              showlegend=False, paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True, key="portfolio_pie")
    if stock_values:
        with cols[1]:
            fig2 = go.Figure(data=[go.Pie(labels=stock_labels, values=stock_values, hole=0.4,
                                           marker=dict(colors=stock_colors, line=dict(color='#fff', width=2)),
                                           textinfo='label+percent', textposition='outside',
                                           textfont=dict(size=11))])
            fig2.update_layout(height=280, margin=dict(l=0, r=0, t=0, b=0),
                               showlegend=False, paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig2, use_container_width=True, key="stock_pie")

    st.markdown('<div class="card"><h3>Positions</h3>', unsafe_allow_html=True)
    if live_portfolio_data:
        df = pd.DataFrame(live_portfolio_data)
        raw_returns = list(df["Return"])
        df["Return"] = df["Return"].map("{:+.2f}%".format)
        def color_col(col):
            return ["color: #059669" if r >= 0 else "color: #dc2626"
                    for r in raw_returns]
        styled = df.style.apply(color_col, subset=["Return"])
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.info("No open positions. Use the Trade tab to allocate your $1,000 starting capital.")
    st.markdown('</div>', unsafe_allow_html=True)
    
    if student_history:
        st.markdown('<div class="card"><h3>Trade History</h3>', unsafe_allow_html=True)
        hist_df = pd.DataFrame(reversed(student_history))
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

with main_tab2:
    if "trade_msg" in st.session_state:
        st.success(f"✅ Trade executed! {st.session_state.trade_msg}")
        del st.session_state.trade_msg
    tcol1, tcol2 = st.columns([1, 1.4])
    
    with tcol1:
        st.markdown('<div class="card"><h3>Trade Ticket</h3>', unsafe_allow_html=True)
        selected_display = stock_picker("trade")
        trade_ticker = selected_display
        live_price = None
        
        if trade_ticker:
            live_price, _, company = fetch_stock_market_data(trade_ticker)
        
        if trade_ticker and live_price is not None:
            st.markdown(f"""
            <div style="margin:-0.5rem 0 0.5rem 0; font-size:0.85rem; color:#374151;">
                {company} · <strong>${live_price:.2f}</strong>
            </div>
            """, unsafe_allow_html=True)
        else:
            if trade_ticker:
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
        
        if trade_ticker and st.button("📋 Review Order", type="primary", use_container_width=True):
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

                error = None
                if action == "Buy" and actual_cost > student_cash:
                    error = f"Insufficient cash (${student_cash:.2f} available, ${actual_cost:.2f} needed)"
                elif action == "Sell":
                    if trade_ticker not in student_holdings:
                        error = "Asset not owned."
                    else:
                        owned_shares = student_holdings[trade_ticker]['shares']
                        if order_mode == "By Shares" and shares_input > owned_shares + 0.0001:
                            error = f"Only {owned_shares:.4f} shares owned."
                        elif order_mode == "By Amount ($)":
                            current_position_value = owned_shares * live_price
                            if usd_allocation > current_position_value + 0.01:
                                error = "Amount exceeds position value."

                if error:
                    st.error(error)
                else:
                    st.session_state.pending_trade = {
                        "action": action, "ticker": trade_ticker, "shares": shares_to_trade,
                        "cost": actual_cost, "price": live_price
                    }
                    st.rerun()

        pending = st.session_state.get("pending_trade")
        if pending and pending["ticker"] == trade_ticker:
            t = pending
            st.info(f"**Confirm {t['action']}:** {t['shares']:.4f} shares of **{t['ticker']}** at ${t['price']:.2f} = **${t['cost']:.2f}**")
            c1, c2 = st.columns(2)
            with c1:
                if st.button(f"✅ Confirm {t['action']}", type="primary", use_container_width=True):
                    live_price, _, _ = fetch_stock_market_data(t['ticker'])
                    if t['action'] == "Buy":
                        student_profile["cash"] = round(student_cash - t['cost'], 2)
                        if t['ticker'] in student_holdings:
                            student_holdings[t['ticker']]['shares'] += t['shares']
                            student_holdings[t['ticker']]['total_cost'] += t['cost']
                        else:
                            student_holdings[t['ticker']] = {'shares': t['shares'], 'total_cost': t['cost']}
                        student_profile.setdefault("history", []).append({
                            "type": "Buy", "ticker": t['ticker'], "shares": round(t['shares'], 4),
                            "price": round(t['price'], 2), "total": round(t['cost'], 2),
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M")
                        })
                        save_student_profile(student_email, student_profile)
                        del st.session_state.pending_trade
                        st.session_state.trade_msg = f"Bought {t['shares']:.4f} shares of {t['ticker']}!"
                        st.rerun()
                    elif t['action'] == "Sell":
                        owned_shares = student_holdings[t['ticker']]['shares']
                        fraction_sold = t['shares'] / owned_shares
                        cost_basis = fraction_sold * student_holdings[t['ticker']]['total_cost']
                        profit = t['cost'] - cost_basis
                        tax = max(0, round(profit * 0.15, 2))
                        net_proceeds = t['cost'] - tax
                        student_profile["unsettled_cash"] = round(student_profile.get("unsettled_cash", 0.0) + net_proceeds, 2)
                        entries = student_profile.get("unsettled_entries", [])
                        entries.append({"amount": net_proceeds, "time": datetime.now().isoformat()})
                        student_profile["unsettled_entries"] = entries
                        student_holdings[t['ticker']]['shares'] -= t['shares']
                        student_holdings[t['ticker']]['total_cost'] -= cost_basis
                        if student_holdings[t['ticker']]['shares'] < 0.0001:
                            del student_holdings[t['ticker']]
                        student_profile.setdefault("history", []).append({
                            "type": "Sell", "ticker": t['ticker'], "shares": round(t['shares'], 4),
                            "price": round(t['price'], 2), "total": round(t['cost'], 2),
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M")
                        })
                        save_student_profile(student_email, student_profile)
                        del st.session_state.pending_trade
                        msg = f"Sold shares of {t['ticker']}!"
                        if tax > 0:
                            msg += f" (15% profit tax: -${tax:.2f})"
                        st.session_state.trade_msg = msg
                        st.rerun()
            with c2:
                if st.button("❌ Cancel", use_container_width=True):
                    del st.session_state.pending_trade
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    with tcol2:
        st.markdown('<div class="card" style="padding:0.5rem 1.25rem 1.25rem 1.25rem;">', unsafe_allow_html=True)
        if trade_ticker:
            trade_chart_period = st.selectbox("Period", options=list(CHART_PERIODS.keys()), format_func=lambda k: CHART_PERIODS[k], key="trade_chart_period", label_visibility="collapsed", index=3)
            hist = fetch_full_history(trade_ticker, period=trade_chart_period)
            if hist is not None and len(hist) > 5:
                fig = plot_candlestick(trade_ticker, hist, period_label=CHART_PERIODS[trade_chart_period])
                fig.update_layout(height=380, margin=dict(l=0, r=0, t=25, b=0))
                st.plotly_chart(fig, use_container_width=True, key="trade_chart")
            else:
                st.info("Not enough data to chart.")
        st.markdown('</div>', unsafe_allow_html=True)

with main_tab3:
    rcol1, rcol2 = st.columns([1, 1])
    
    with rcol1:
        st.markdown('<div class="card"><h3>Volatility Calculator</h3>', unsafe_allow_html=True)
        vol_ticker = stock_picker("vol")
        vol_period = st.selectbox("Period", ["10d", "1mo", "3mo", "6mo", "1y"], key="vol_period", label_visibility="collapsed")
        if vol_ticker:
            try:
                vol_data = _flatten_cols(yf.download(vol_ticker, period=vol_period, progress=False))
            except Exception:
                vol_data = None
        if vol_ticker is not None and vol_data is not None and len(vol_data) >= 2:
            vol_data['Daily Change (%)'] = vol_data['Close'].pct_change() * 100
            clean = vol_data[['Close', 'Daily Change (%)']].dropna()
            std = clean['Daily Change (%)'].std()
            period_label = {"10d": "10 days", "1mo": "1 month", "3mo": "3 months", "6mo": "6 months", "1y": "1 year"}.get(vol_period, vol_period)
            st.markdown(f"""
            <div class="metric-row">
                <div class="metric-box">
                    <div class="m-label">Daily Volatility</div>
                    <div class="m-value">{std:.2f}%</div>
                </div>
                <div class="metric-box">
                    <div class="m-label">Typical Range ({period_label})</div>
                    <div class="m-value">±{std:.2f}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            risk = "very low" if std < 0.5 else "low" if std < 1.0 else "moderate" if std < 1.5 else "high" if std < 2.5 else "very high"
            st.caption(
                f"**What this means:** {vol_ticker} typically moves **±{std:.1f}%** per day. "
                f"Risk level: **{risk}**. "
                f"Volatility measures how much a stock's price jumps around day-to-day. "
                f"Higher volatility = less predictable price = bigger potential swings both ways."
            )
        else:
            st.info("Pick a stock to calculate volatility.")
        st.markdown('</div>', unsafe_allow_html=True)
    
    with rcol2:
        st.markdown('<div class="card"><h3>Price History</h3>', unsafe_allow_html=True)
        if vol_ticker:
            live_pr, _, comp = fetch_stock_market_data(vol_ticker)
            if live_pr is not None:
                st.markdown(f'<div style="font-size:2rem;font-weight:700;margin-bottom:0.5rem">${live_pr:.2f} <span style="font-size:0.9rem;font-weight:400;color:#6b7280">{comp}</span></div>', unsafe_allow_html=True)
            research_chart_period = st.selectbox("Period", options=list(CHART_PERIODS.keys()), format_func=lambda k: CHART_PERIODS[k], key="research_chart_period", label_visibility="collapsed", index=3)
            hist2 = fetch_full_history(vol_ticker, period=research_chart_period)
            if hist2 is not None and len(hist2) > 5:
                fig2 = plot_candlestick(vol_ticker, hist2, period_label=CHART_PERIODS[research_chart_period])
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
        alert_ticker = stock_picker("alert")
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
            save_student_profile(student_email, student_profile)
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
                save_student_profile(student_email, student_profile)
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# 6. ENHANCED TEACHER ADMIN & CLASS LEADERBOARD
# ==========================================

if student_email == config_teacher_email:
    st.write("---")
    st.markdown('<div class="card"><h3>👨‍🏫 Teacher Administration</h3></div>', unsafe_allow_html=True)

    admin_tab1, admin_tab2 = st.tabs(["📊 Classroom Standings", "🧪 My Pilot Testing"])

    with st.spinner("Loading classroom data..."):
        all_portfolios = get_gcs_database()

    if all_portfolios:
        with admin_tab1:
            records = []
            for email, profile in all_portfolios.items():
                if email == config_teacher_email:
                    continue
                name = profile.get("name", "Unknown")
                cash = profile.get("cash", 1000.0)
                holdings = profile.get("holdings", {})
                history = profile.get("history", [])

                mv = 0.0
                for ticker, pos in holdings.items():
                    p, _, _ = fetch_stock_market_data(ticker)
                    if p is not None:
                        mv += pos["shares"] * p

                nw = cash + mv
                pl = nw - 1000.0
                pr = (pl / 1000.0) * 100

                records.append({
                    "Rank": 0, "Student": name, "Email": email,
                    "Net Worth": nw, "P&L ($)": pl, "Return (%)": pr,
                    "Cash": cash, "Stock Value": mv, "Trades": len(history)
                })

            if records:
                df = pd.DataFrame(records)
                df = df.sort_values("Net Worth", ascending=False).reset_index(drop=True)
                df["Rank"] = df.index + 1
                for c in ["Net Worth", "P&L ($)", "Cash", "Stock Value"]:
                    df[c] = df[c].map("${:,.2f}".format)
                df["Return (%)"] = df["Return (%)"].map("{:+.2f}%".format)
                st.dataframe(df, use_container_width=True, hide_index=True)

                c1, c2 = st.columns(2)
                c1.metric("Active Students", len(df))
                top = df.iloc[0]
                c2.metric("Class Leader", top["Student"], top["Return (%)"])
            else:
                st.info("No student accounts found yet.")

        with admin_tab2:
            st.markdown("#### 🧪 Your Sandbox Status")
            st.info("Your personal trading is handled in the main tabs above, filtered out of classroom standings.")
            teacher_profile = all_portfolios.get(config_teacher_email)
            if teacher_profile:
                st.json({
                    "Name": teacher_profile.get("name"),
                    "Cash": f"${teacher_profile.get('cash', 0.0):,.2f}",
                    "Holdings": {t: p['shares'] for t, p in teacher_profile.get("holdings", {}).items()},
                    "Trades Made": len(teacher_profile.get("history", []))
                })
    else:
        st.error("Could not load classroom data.")
