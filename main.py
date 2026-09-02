from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from threading import Lock

import pandas as pd
import plotly.graph_objects as go
import requests
import yfinance as yf
from cachetools import TTLCache
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from nicegui import app, ui

from services.profile import (
    _check_alerts,
    _clean_dust_holdings,
    _get,
    _migrate_profile,
    _portfolio,
    _process_dividends,
    _process_settlement,
    _process_weekly,
    _profile_locks,
    _profiles,
    _save,
)
from utils.auth import exchange_code, get_auth_url, is_teacher
from utils.helpers import (
    STARTING_CASH_CENTS,
    _cents,
    _fmt,
    _relative_time,
    _require_env,
)
from utils.market import (
    ALL_TICKERS,
    CHART_PERIODS,
    ETF_TICKERS,
    STOCK_TICKERS,
    _flatten_cols,
    fetch_full_history,
    fetch_stock_market_data,
    format_ticker_option,
    get_price_source,
    get_top_movers,
    movers_load_action,
    warm_price_cache,
)
from utils.storage import (
    _safe_email_key,
    delete_student_profile,
    delete_student_profile_by_key,
    get_gcs_database,
    load_class_settings,
    save_class_settings,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NEWS_WHITELIST: set[str] = {
    "Reuters",
    "Bloomberg",
    "The Associated Press",
    "CNBC",
    "MarketWatch",
    "The Wall Street Journal",
    "Financial Times",
    "Barron's",
    "Yahoo Finance",
    "Forbes",
    "Fortune",
    "Business Insider",
    "Money",
    "PR Newswire",
    "Business Wire",
    "GlobeNewswire",
    "Accesswire",
    "TechCrunch",
    "Ars Technica",
    "The Verge",
}


_executor = ThreadPoolExecutor(max_workers=16)
_session_store: dict[str, dict] = {}
_session_lock = Lock()
_movers_cache: dict = {"data": [], "loaded": False, "ts": 0.0, "loading": False}
_MOVERS_TTL = 300.0
_warm_lock = Lock()
_warm_state: dict = {"ts": 0.0}
_WARM_TTL = 60.0

# Curfew: app unavailable outside classroom hours (Guam = UTC+10, no DST).
# Closed window: 11:00 UTC -> 22:00 UTC (9pm -> 8am next day Guam time).
_CURFEW_OPEN_UTC_HOUR = 22   # 8:00 AM Guam
_CURFEW_CLOSE_UTC_HOUR = 11  # 9:00 PM Guam (day before)
_IDLE_TIMEOUT = 900          # 15 minutes of real user inactivity -> disconnect


def _in_curfew(utc_now: datetime | None = None) -> bool:
    """True if Guam local time is inside 9pm-8am (closed window).

    Open (allows access): 22:00 UTC -> 11:00 UTC next day (8am-9pm Guam).
    Closed: 11:00 UTC -> 22:00 UTC (9pm-8am Guam).
    UTC-10 = Guam with no DST, so a fixed UTC hour window holds year-round.
    """
    utc_now = utc_now or datetime.utcnow()
    hour = utc_now.hour
    return _CURFEW_CLOSE_UTC_HOUR <= hour < _CURFEW_OPEN_UTC_HOUR



def _touch_session():
    token = app.storage.user.get("_token", "")
    if token:
        with _session_lock:
            session = _session_store.get(token)
            if session:
                session["last_activity"] = datetime.utcnow().timestamp()


def _touch_client_activity():
    """Record real, user-driven client activity (distinct from timer pings)."""
    token = app.storage.user.get("_token", "")
    if token:
        with _session_lock:
            session = _session_store.get(token)
            if session:
                session["last_client_activity"] = datetime.utcnow().timestamp()


def _get_session(key: str, default=None):
    token = app.storage.user.get("_token", "")
    if token:
        with _session_lock:
            session = _session_store.get(token)
            if session:
                return session.get(key, default)
    return default


def _clear_session():
    token = app.storage.user.get("_token", "")
    with _session_lock:
        _session_store.pop(token, None)


def _prewarm_movers():
    stock_groups = [
        STOCK_TICKERS[i : i + 100]
        for i in range(0, len(STOCK_TICKERS), 100)
    ]
    for group in stock_groups + [ETF_TICKERS]:
        try:
            get_top_movers(tuple(group))
        except Exception:
            pass


raw_proxies = os.environ.get("TRUSTED_PROXY_IPS", "")
TRUSTED_PROXIES = set(filter(None, raw_proxies.split(",")))
if not TRUSTED_PROXIES:
    logger.warning("TRUSTED_PROXY_IPS not set — X-Forwarded-For will NOT be validated")

def _get_client_ip(request: Request = None) -> str:
    try:
        if not request:
            try:
                request = ui.context.client.request
            except Exception:
                return "unknown"
        actual_ip = request.client.host if request.client else "unknown"
        if actual_ip in TRUSTED_PROXIES or not TRUSTED_PROXIES:
             xff = request.headers.get("x-forwarded-for")
             if xff:
                 return xff.split(",")[0].strip()
        return actual_ip
    except Exception:
        return "unknown"

def _audit(event: str, email: str, details: dict | None = None, ip: str | None = None):
    if not ip:
        ip = _get_client_ip()
    logger.info(
        json.dumps(
            {
                "event": event,
                "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "user": email,
                "ip": ip,
                "details": details or {},
            }
        )
    )

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: https:;"
    return response


_callback_rates = TTLCache(maxsize=10000, ttl=60)


_MACRO_CACHE = {"ts": 0, "data": None}
_MACRO_TTL = 86400


def _fetch_macro() -> dict:
    now = datetime.now()
    if (
        now.timestamp() - _MACRO_CACHE["ts"] < _MACRO_TTL
        and _MACRO_CACHE["data"] is not None
    ):
        return _MACRO_CACHE["data"]
    frd_to = now.strftime("%Y-%m-%d")
    frd_from = now.replace(year=now.year - 2).strftime("%Y-%m-%d")

    def _vix():
        d = _flatten_cols(yf.download("^VIX", period="2y", progress=False, timeout=15))
        v = d["Close"].dropna()
        if not v.empty:
            vv = v.iloc[-1]
            return (
                "vix",
                f"{vv:.2f}",
                "vix_color",
                ("positive" if vv < 15 else "warning" if vv < 25 else "negative"),
            )
        return "vix", "N/A", "vix_color", ""

    def _dxy():
        d = _flatten_cols(
            yf.download("DX-Y.NYB", period="1mo", progress=False, timeout=15)
        )
        s = d["Close"].dropna()
        if not s.empty:
            dv = s.iloc[-1]
            chg = ((dv / s.iloc[0]) - 1) * 100
            return "dxy", f"{dv:.2f}", "dxy_chg", f"{chg:+.1f}%"
        return "dxy", "N/A", "dxy_chg", ""

    def _fred(key, series):
        try:
            r = requests.get(
                f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={frd_from}&coed={frd_to}",
                timeout=10,
            )
            df = pd.read_csv(io.StringIO(r.text))
            vals = df.iloc[:, 1].dropna()
            if len(vals) >= 13:
                yoy = ((vals.iloc[-1] / vals.iloc[-13]) - 1) * 100
                return (
                    key,
                    f"{yoy:+.1f}%",
                    f"{key}_color",
                    ("positive" if yoy < 0 else "negative"),
                )
            return key, "N/A", f"{key}_color", ""
        except Exception:
            return key, "N/A", f"{key}_color", ""

    futs = [_executor.submit(_vix), _executor.submit(_dxy)]
    futs += [
        _executor.submit(_fred, k, s)
        for k, s in [("cpi", "CPIAUCNS"), ("ppi", "PPIFID"), ("pce", "PCEPI")]
    ]
    result = {}
    for f in futs:
        try:
            r = f.result()
            if r[0] == "dxy":
                result["dxy"] = r[1]
                result["dxy_chg"] = r[3]
            else:
                result[r[0]] = r[1]
                result[r[2]] = r[3]
        except Exception:
            pass
    if result and len(result) >= 3:
        _MACRO_CACHE["ts"] = now.timestamp()
        _MACRO_CACHE["data"] = result
        return result
    if _MACRO_CACHE["data"] is not None:
        return _MACRO_CACHE["data"]
    return result


# ── Fonts (Quasar needs Material Icons internally) ───────
ui.add_head_html(
    '<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">',
    shared=True,
)
ui.add_head_html(
    '<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>',
    shared=True,
)

# ── CSS Design System ─────────────────────────────────────
ui.add_css(
    """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/icon?family=Material+Icons');

:root {
  --bg: #f8fafc;
  --surface: #ffffff;
  --primary: #2563eb;
  --primary-hover: #1d4ed8;
  --text: #1e293b;
  --text-secondary: #64748b;
  --text-muted: #94a3b8;
  --border: #e5e7eb;
  --positive: #22c55e;
  --negative: #ef4444;
  --warning: #f59e0b;
  --radius: 12px;
  --radius-sm: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,0.06);
  --shadow-hover: 0 4px 12px rgba(0,0,0,0.1);
  --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

body { background: var(--bg); margin: 0; font-family: var(--font); }
.material-icons { font-family: 'Material Icons' !important; font-feature-settings: 'liga'; font-weight: 400; font-style: normal; }

/* ── Top Bar ────────────────────────────────── */
.topbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.75rem 1.5rem; background: var(--surface);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow);
}
.topbar h1 { font-size: 1.25rem; font-weight: 700; color: var(--text); margin: 0; }
.user-badge { display: flex; align-items: center; gap: 6px; }
.user-badge .name { color: var(--text); font-size: 0.875rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px; }
.user-badge .email { color: var(--text-muted); font-size: 0.75rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 150px; }
.user-badge .sep { color: var(--text-muted); opacity: 0.4; }
.user-badge .signout { color: var(--text-muted); font-size: 0.75rem; text-decoration: none; cursor: pointer; }
.user-badge .signout:hover { color: #ef4444; }

/* ── Summary Bar ────────────────────────────── */
.psummary {
  display: flex; gap: 0.75rem; padding: 1rem 1.5rem;
  background: var(--surface); border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow); flex-wrap: wrap;
}
.metric-box {
  flex: 1; min-width: 120px; text-align: center;
}
.metric-box .label {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.5px;
  color: var(--text-muted); font-weight: 500;
}
.metric-box .value {
  font-size: 1.2rem; font-weight: 700; color: var(--text); margin-top: 2px;
}
.metric-box .sub {
  font-size: 0.7rem; font-weight: 600; margin-top: 1px;
}

/* ── Cards ──────────────────────────────────── */
.card {
  background: var(--surface); border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 1.25rem;
  transition: box-shadow 0.2s;
}
.card:hover { box-shadow: var(--shadow-hover); }

/* ── Page Container ─────────────────────────── */
.page-container {
  max-width: 1280px; width: 100%; box-sizing: border-box;
  margin: 0 auto; padding: 0 1rem;
}

/* ── Notifications / Deposit Banner ─────────── */
.banner { border-radius: var(--radius-sm); padding: 0.5rem 1rem; font-size: 0.875rem; font-weight: 500; margin: 0.5rem 1.5rem 0; }
.banner-positive { background: #f0fdf4; border: 1px solid #86efac; color: #166534; }
.banner-warning { background: #fffbeb; border: 1px solid #fde68a; color: #92400e; }

/* ── Tabs ────────────────────────────────────── */
.q-tab { font-size: 0.9rem; font-weight: 500; }
.q-tab--active { color: var(--primary) !important; font-weight: 600; }
.q-tabs__arrow { display: none !important; }

/* ── Tables ──────────────────────────────────── */
.q-table th {
  font-weight: 600; font-size: 0.75rem; text-transform: uppercase;
  letter-spacing: 0.5px; color: var(--text-secondary);
}
.q-table td { font-size: 0.875rem; vertical-align: middle; }

/* ── Buttons ─────────────────────────────────── */
.q-btn { border-radius: var(--radius-sm); font-weight: 600; transition: all 0.15s; }
.q-btn:hover { transform: translateY(-1px); }

/* ── Text Utilities ─────────────────────────── */
.text-positive { color: var(--positive); }
.text-negative { color: var(--negative); }
.text-warning { color: var(--warning); }
.text-muted { color: var(--text-muted); }
.text-sm { font-size: 0.875rem; }
.text-xs { font-size: 0.75rem; }

/* ── Pie Chart Container ────────────────────── */
.chart-container {
  flex: 1; display: flex; align-items: center; justify-content: center;
}

/* ── Trade Ticket / Market Movers ───────────── */
.trade-ticket, .market-movers { flex: 1; }

/* ── Alert Row ───────────────────────────────── */
.alert-row { display: flex; align-items: center; gap: 0.75rem; padding: 0.5rem 0; border-bottom: 1px solid var(--border); }

/* ── Research Tab ────────────────────────────── */
.research-vol { flex: 0 0 33%; min-width: 280px; }
.research-chart { flex: 1; min-width: 400px; }

/* ── Responsive ──────────────────────────────── */
@media (max-width: 640px) {
  .topbar { flex-direction: column; gap: 0.5rem; }
  .topbar h1 { font-size: 1rem; }
  .user-badge .email { display: none; }
  .psummary { flex-direction: column; }
  .metric-box { min-width: 100%; }
  .trade-ticket, .market-movers { flex: none; width: 100%; }
  .page-container { padding: 0 0.5rem; }
  .research-vol, .research-chart { flex: none; width: 100%; }
}
""",
    shared=True,
)


# ── OAuth routes ─────────────────────────────────────────
@app.get("/login")
async def login_route(request: Request):
    redirect_uri = _get_redirect_uri(request)
    auth_url, state, code_verifier = get_auth_url(redirect_uri=redirect_uri)
    app.storage.user["oauth_state"] = state
    app.storage.user["oauth_code_verifier"] = code_verifier
    return RedirectResponse(auth_url)


def _get_redirect_uri(request):
    env_uri = os.environ.get("REDIRECT_URI", "").strip()
    if env_uri:
        return env_uri
    base = str(request.base_url).strip()
    if "run.app" in base:
        return base.replace("http://", "https://").rstrip("/") + "/callback"
    return "http://localhost:8080/callback"


@app.get("/callback")
async def callback_route(code: str, request: Request, state: str = None):
    client_ip = _get_client_ip(request)
    now = datetime.utcnow().timestamp()

    attempts = _callback_rates.get(client_ip, [])
    attempts = [t for t in attempts if now - t < 60]
    if len(attempts) >= 5:
        return HTMLResponse("Too Many Requests", status_code=429)
    attempts.append(now)
    _callback_rates[client_ip] = attempts

    redirect_uri = _get_redirect_uri(request)
    stored_state = app.storage.user.get("oauth_state")
    if not stored_state or not state or state != stored_state:
        logger.warning("OAuth state mismatch")
        _audit("LOGIN_FAILED", "anonymous", {"reason": "state_mismatch"}, ip=client_ip)
        return HTMLResponse(
            """
            <h2 style="color:#ef4444;font-family:sans-serif">Authentication failed</h2>
            <p style="font-family:sans-serif;color:#6b7280">Authentication failed. Please try again.</p>
            <a href="/" style="color:#2563eb">Try again</a>
        """,
            status_code=400,
        )
    try:
        code_verifier = app.storage.user.get("oauth_code_verifier", "")
        user_info = exchange_code(code, code_verifier, redirect_uri=redirect_uri)
        app.storage.user["oauth_state"] = ""
        app.storage.user["oauth_code_verifier"] = ""
        email = user_info["email"]
        if _in_curfew() and not is_teacher(email):
            _audit("LOGIN_BLOCKED_CURFEW", email, ip=client_ip)
            return HTMLResponse(
                """
                <h2 style="color:#ef4444;font-family:sans-serif">Market closed</h2>
                <p style="font-family:sans-serif;color:#6b7280">The simulator is available 8:00 AM &ndash; 9:00 PM (Chamorro Time). Please try again then.</p>
                <a href="/" style="color:#2563eb">Back to app</a>
            """
            )
        token = secrets.token_urlsafe(32)
        with _session_lock:
            _session_store[token] = {
                "authenticated": True,
                "email": user_info["email"],
                "name": user_info.get("name", "Student"),
                "ip": client_ip,
                "last_activity": datetime.utcnow().timestamp(),
            }
        app.storage.user["_token"] = token
        # Remove sensitive fields from the on-disk session file
        for k in ("authenticated", "email", "name", "ip", "last_activity"):
            app.storage.user.pop(k, None)
        _audit("LOGIN", user_info["email"], ip=client_ip)
        _executor.submit(_get, user_info["email"])
        return RedirectResponse("/")
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        _audit("LOGIN_FAILED", "anonymous", {"reason": str(e)}, ip=client_ip)
        return HTMLResponse(
            """
            <h2 style="color:#ef4444;font-family:sans-serif">Authentication failed</h2>
            <p style="font-family:sans-serif;color:#6b7280">Authentication failed. Please try again.</p>
            <a href="/" style="color:#2563eb">Try again</a>
        """
        )


@app.get("/logout")
async def logout_route():
    token = app.storage.user.get("_token", "")
    if token:
        with _session_lock:
            _session_store.pop(token, None)
    app.storage.user.clear()
    _audit("LOGOUT", app.storage.user.get("email", "anonymous"))
    return RedirectResponse("/")


@app.post("/_activity")
async def activity_route(request: Request):
    """Record real client activity (mousemove/keydown/click/touch) for idle tracking."""
    try:
        body = await request.json()
        token = (body or {}).get("token", "")
        if token:
            with _session_lock:
                session = _session_store.get(token)
                if session:
                    session["last_client_activity"] = datetime.utcnow().timestamp()
    except Exception:
        pass
    return Response(status_code=204)


# ── Legal pages ──────────────────────────────────────────
@ui.page("/privacy")
def privacy_page():
    with ui.column().classes("items-center min-h-screen bg-gray-50"):
        with ui.column().classes("max-w-3xl w-full p-8"):
            ui.link("← Back to App", "/").classes("text-blue-600 mb-4")
            ui.label("Math Finance Simulator").classes("text-2xl font-bold")
            ui.label("Privacy Policy").classes("text-xl font-semibold mt-4")
            ui.label("Last updated: May 29, 2026").classes("text-gray-500 text-sm")
            ui.separator().classes("my-4")
            for title, items in [
                (
                    "Information We Collect",
                    [
                        "Your Google Account information (name, email) for identification.",
                        "Portfolio data (trades, holdings, cash balance) stored in Google Cloud Storage.",
                    ],
                ),
                (
                    "How We Use Your Information",
                    [
                        "To provide and maintain the stock market simulation.",
                        "To persist your data across sessions.",
                        "To display classroom standings to your instructor.",
                    ],
                ),
                (
                    "Third-Party Services",
                    [
                        "Google Workspace (authentication only)",
                        "Google Cloud Storage (data persistence)",
                        "Yahoo Finance via yfinance (stock price data and news)",
                        "Federal Reserve Economic Data / FRED (CPI, PPI, PCE indicators)",
                    ],
                ),
            ]:
                ui.label(title).classes("text-lg font-semibold mt-4")
                for item in items:
                    ui.label(f"\u2022 {item}").classes("text-gray-700 ml-4")
            ui.link("← Back to App", "/").classes("text-blue-600 mt-8")


@ui.page("/terms")
def terms_page():
    with ui.column().classes("items-center min-h-screen bg-gray-50"):
        with ui.column().classes("max-w-3xl w-full p-8"):
            ui.link("← Back to App", "/").classes("text-blue-600 mb-4")
            ui.label("Math Finance Simulator").classes("text-2xl font-bold")
            ui.label("Terms of Service").classes("text-xl font-semibold mt-4")
            ui.label("Last updated: May 29, 2026").classes("text-gray-500 text-sm")
            ui.separator().classes("my-4")
            for title, items in [
                ("Acceptance", ["Educational simulation for classroom use only."]),
                (
                    "Educational Purpose Only",
                    [
                        "Simulation using delayed data from Yahoo Finance.",
                        "Stock news provided by Yahoo Finance via yfinance.",
                        "Macroeconomic indicators (CPI, PPI, PCE) provided by FRED.",
                        "All trades are fictional \u2014 no real money is involved.",
                    ],
                ),
                (
                    "User Responsibilities",
                    [
                        "Use your school-provided Google Workspace account.",
                        "Do not access other users' data.",
                    ],
                ),
                (
                    "Access Hours",
                    [
                        "The simulator is available 8:00 AM \u2013 9:00 PM (Chamorro Time).",
                        "Sessions idle for more than 15 minutes are automatically signed out.",
                    ],
                ),
            ]:
                ui.label(title).classes("text-lg font-semibold mt-4")
                for item in items:
                    ui.label(f"\u2022 {item}").classes("text-gray-700 ml-4")
            ui.link("← Back to App", "/").classes("text-blue-600 mt-8")


def _validate_trade_inputs(ticker, price, action, mode, shares_val, amount_val, profile, all_tickers):
    if not ticker:
        return False, "Select a ticker", None
    if price is None:
        return False, f"Price unavailable for {ticker}", None
    if ticker not in all_tickers:
        return False, f"Invalid ticker: {ticker}", None
    cost = (shares_val * price) if mode == "Shares" else amount_val
    cost_c = _cents(cost)
    sh = shares_val if mode == "Shares" else cost / price
    err = None
    if action == "Buy" and cost_c > profile.get("cash", 0):
        err = f'Insufficient cash ({_fmt(profile["cash"])} available, {_fmt(cost_c)} needed)'
    elif action == "Sell":
        if ticker not in profile.get("holdings", {}):
            err = "Not owned."
        else:
            o = profile["holdings"][ticker]["shares"]
            if mode == "Shares" and sh > o + 0.0001:
                err = f"Only {o:.4f} shares owned."
            elif mode == "Amount ($)" and cost > o * price + 0.01:
                err = "Exceeds position value."
    if err:
        return False, err, None
    return True, "", {"action": action, "ticker": ticker, "shares": sh, "cost": cost, "price": price}


def _execute_trade(data, profile, email, locks_dict, save_fn, all_tickers):
    t = data.get("ticker", "")
    if t not in all_tickers:
        return False, "Invalid ticker.", None, None
    if data.get("action") not in ("Buy", "Sell"):
        return False, "Invalid action.", None, None
    if data.get("shares", 0) <= 0 or data.get("cost", 0) <= 0:
        return False, "Invalid trade: shares and cost must be positive.", None, None
    live_price, _, _ = fetch_stock_market_data(t)
    if live_price is not None:
        drift = abs(data["price"] - live_price) / live_price
        if drift > 0.02:
            return False, f'Price changed from ${data["price"]:.2f} to ${live_price:.2f} ({(drift*100):.1f}%). Please re-review.', None, None
    lock = locks_dict.setdefault(email, Lock())
    with lock:
        d_shares = Decimal(str(data["shares"]))
        d_price = Decimal(str(data["price"]))
        cost_c = int((d_shares * d_price * 100).to_integral_value(ROUND_HALF_UP))
        if data["action"] == "Buy":
            if profile.get("cash", 0) < cost_c:
                return False, "Insufficient cash.", None, None
            profile["cash"] -= cost_c
            if t in profile["holdings"]:
                profile["holdings"][t]["shares"] += data["shares"]
                profile["holdings"][t]["total_cost"] += cost_c
            else:
                profile["holdings"][t] = {"shares": data["shares"], "total_cost": cost_c}
            profile.setdefault("history", []).append({"type": "Buy", "ticker": t, "shares": round(data["shares"], 4), "price": round(data["price"], 2), "total": round(data["cost"], 2), "cost_basis": "", "tax": "", "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
            details = {"ticker": t, "shares": round(data["shares"], 4), "price": round(data["price"], 2), "cost_cents": cost_c}
        else:
            if t not in profile.get("holdings", {}) or profile["holdings"][t]["shares"] < data["shares"]:
                return False, "Insufficient shares.", None, None
            owned = profile["holdings"][t]["shares"]
            frac = data["shares"] / owned
            cb = int(round(frac * profile["holdings"][t]["total_cost"]))
            profit_c = cost_c - cb
            tax_c = max(0, int(round(profit_c * 0.15)))
            net_c = cost_c - tax_c
            profile["unsettled_cash"] = profile.get("unsettled_cash", 0) + net_c
            profile.setdefault("unsettled_entries", []).append({"amount": net_c, "time": datetime.now().isoformat()})
            profile["holdings"][t]["shares"] -= data["shares"]
            profile["holdings"][t]["total_cost"] -= cb
            if profile["holdings"][t]["shares"] <= 1e-6 or profile["holdings"][t]["total_cost"] <= 0:
                del profile["holdings"][t]
            profile.setdefault("history", []).append({"type": "Sell", "ticker": t, "shares": round(data["shares"], 4), "price": round(data["price"], 2), "total": round(data["cost"], 2), "cost_basis": round(cb / 100.0, 2), "tax": round(tax_c / 100.0, 2), "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
            details = {"ticker": t, "shares": round(data["shares"], 4), "price": round(data["price"], 2), "net_cents": net_c, "tax_cents": tax_c}
        if profile["cash"] < 0:
            raise RuntimeError(f"Negative cash after trade: {profile['cash']} (email={email}, ticker={t})")
        save_fn(email, profile)
    return True, None, data["action"], details


# ── Main page ────────────────────────────────────────────
def _render_curfew_block(show_teacher_login: bool = False):
    with ui.column().classes("items-center justify-center min-h-screen gap-6"):
        ui.label("\U0001f515").classes("text-6xl")
        ui.label("Math Finance Simulator").classes("text-3xl font-bold text-gray-800")
        ui.label("The market is closed for the day.").classes("text-gray-500 text-lg")
        ui.label("Available 8:00 AM \u2013 9:00 PM (Chamorro Time).").classes(
            "text-gray-500"
        )
        if show_teacher_login:
            with ui.column().classes("items-center gap-2"):
                ui.label("Teachers: use the button below to sign in during off hours.").classes(
                    "text-sm text-gray-400"
                )
                ui.button("Sign in as teacher", on_click=_teacher_curfew_login).classes(
                    "bg-blue-600 text-white px-6 py-2 rounded-lg hover:bg-blue-700"
                )
        with ui.row().classes("gap-4 mt-8 text-sm text-gray-400"):
            ui.link("Privacy Policy", "/privacy")
            ui.link("Terms of Service", "/terms")


def _teacher_curfew_login():
    """Redirect a (presumably teacher) visitor to Google auth during curfew."""
    request = ui.context.client.request
    redirect_uri = _get_redirect_uri(request)
    login_url, state, code_verifier = get_auth_url(redirect_uri=redirect_uri)
    app.storage.user["oauth_state"] = state
    app.storage.user["oauth_code_verifier"] = code_verifier
    ui.navigate.to(login_url)


@ui.page("/")
async def main_page():
    now = datetime.utcnow().timestamp()
    last_activity = _get_session("last_activity")
    if last_activity and now - last_activity > 1800:
        _clear_session()
        app.storage.user.clear()

    if not _get_session("authenticated"):
        if _in_curfew():
            _render_curfew_block(show_teacher_login=True)
            return
        request = ui.context.client.request
        redirect_uri = _get_redirect_uri(request)
        login_url, state, code_verifier = get_auth_url(redirect_uri=redirect_uri)
        app.storage.user["oauth_state"] = state
        app.storage.user["oauth_code_verifier"] = code_verifier
        with ui.column().classes("items-center justify-center min-h-screen gap-6"):
            ui.label("\U0001f4c8").classes("text-6xl")
            ui.label("Math Finance Simulator").classes(
                "text-3xl font-bold text-gray-800"
            )
            ui.label("Classroom Stock Market Simulation").classes(
                "text-gray-500 text-lg"
            )
            ui.link("Sign in with Google Workspace", target=login_url).classes(
                "bg-blue-600 text-white px-8 py-3 rounded-xl shadow-lg hover:shadow-xl text-lg font-semibold no-underline inline-block text-center"
            )
            with ui.row().classes("gap-4 mt-8 text-sm text-gray-400"):
                ui.link("Privacy Policy", "/privacy")
                ui.link("Terms of Service", "/terms")
        return

    # ── Load profile ──
    _touch_session()
    email = _get_session("email")
    if _in_curfew() and not is_teacher(email):
        _render_curfew_block()
        return
    name = _get_session("name", "Student")
    _token = app.storage.user.get("_token", "")
    _touch_client_activity()
    ui.run_javascript(
        f"""
        (function() {{
            var tok = {json.dumps(_token)};
            var pending = false;
            var report = function() {{
                if (pending) return;
                pending = true;
                fetch('/_activity', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{token: tok}})
                }}).finally(function() {{ pending = false; }});
            }};
            var evs = ['mousemove','keydown','click','touchstart','wheel'];
            for (var i = 0; i < evs.length; i++) {{
                window.addEventListener(evs[i], report, {{passive: true}});
            }}
            if (document.visibilityState === 'visible') report();
        }})();
        """
    )
    loop = asyncio.get_event_loop()
    profile = await loop.run_in_executor(_executor, _get, email)
    if profile is None:
        profile = {
            "name": name,
            "cash": STARTING_CASH_CENTS,
            "holdings": {},
            "alerts": [],
            "history": [],
            "unsettled_cash": 0,
            "unsettled_entries": [],
            "dividend_tracker": {},
            "total_dividends_earned": 0,
        }
        _save(email, profile)
    profile["name"] = name
    profile.setdefault("total_dividends_earned", 0)

    # Warm price cache for current user's holdings and alerts (deduped — cache is shared)
    try:
        import time as _warm_time

        with _warm_lock:
            if _warm_time.time() - _warm_state["ts"] >= _WARM_TTL:
                _warm_state["ts"] = _warm_time.time()
                tickers_to_warm = set()
                for t in profile.get("holdings", {}).keys():
                    tickers_to_warm.add(t)
                for a in profile.get("alerts", []):
                    tickers_to_warm.add(a["ticker"])
                if tickers_to_warm:
                    _executor.submit(warm_price_cache, list(tickers_to_warm))
                else:
                    _warm_state["ts"] = 0.0
        # Pre-fill market movers cache — only warm yfinance TTL; _load_movers owns _movers_cache
        if not _movers_cache["loaded"] and not _movers_cache["loading"]:
            _executor.submit(_prewarm_movers)
    except Exception as e:
        logger.error(f"Error warming price cache: {e}")

    # ── Top Bar ──
    ui.html(
        f"""
    <div class="topbar">
        <h1>\U0001f4c8 Math Finance Simulator</h1>
        <div class="user-badge">
            <span class="name">\U0001f464 {html.escape(name)}</span>
            <span class="sep">|</span>
            <span class="email">{html.escape(email)}</span>
            <span class="sep">|</span>
            <a href="/logout" class="signout">Sign Out</a>
        </div>
    </div>
    """,
        sanitize=False,
    )

    # ── Summary Bar ──
    _summary_state = {"data": None}

    @ui.refreshable
    def summary():
        p = _summary_state["data"]
        if p is None:
            ui.html(
                '<div class="psummary"><div class="metric-box">Loading...</div></div>',
                sanitize=False,
            )
            return
        sign = "+" if p["pl"] >= 0 else ""
        cls = "text-positive" if p["pl"] >= 0 else "text-negative"
        pl_str = f"{sign}${p['pl']:,.2f} ({p['pl_pct']:+.2f}%)"
        items_html = (
            f'<div class="metric-box"><div class="label">Cash Balance</div><div class="value">${p["cash"]:,.2f}</div></div>'
            f'<div class="metric-box"><div class="label">Unsettled Cash</div><div class="value text-warning">${p["unsettled"]:,.2f}</div>'
            + (f'<div class="sub text-muted" style="font-size:0.7em">Available after market close</div>' if p["unsettled"] > 0 else '')
            + '</div>'
            f'<div class="metric-box"><div class="label">Invested</div><div class="value">${p["total_hold"]:,.2f}</div><div class="sub {cls}">{pl_str}</div></div>'
            f'<div class="metric-box"><div class="label">Dividends</div><div class="value text-positive">{_fmt(profile.get("total_dividends_earned", 0))}</div></div>'
            f'<div class="metric-box"><div class="label">Total Account</div><div class="value">${p["total"]:,.2f}</div></div>'
        )
        ui.html(f'<div class="psummary">{items_html}</div>', sanitize=False)

    async def _load_summary():
        loop = asyncio.get_event_loop()
        try:
            _summary_state["data"] = await loop.run_in_executor(_executor, _portfolio, profile)
        except Exception as e:
            logger.error(f"Portfolio summary load failed: {e}")
            _summary_state["data"] = {"cash": 0, "unsettled": 0, "total_hold": 0, "pl": 0, "pl_pct": 0.0, "total": 0}
        summary.refresh()
        try:
            positions_info.refresh()
        except Exception:
            pass

    summary()
    ui.timer(0.1, _load_summary, once=True)

    # Refreshable banners — deposit shown after async processing, alerts appear when ready
    _alert_msgs: list[str] = []
    _deposit_state: dict = {"amt": None, "weeks": 0}

    @ui.refreshable
    def banner_area():
        da = _deposit_state["amt"]
        if da:
            ui.html(
                f'<div class="banner banner-positive">\U0001f4b0 Weekly deposit: +{_fmt(da)} ({_deposit_state["weeks"]} week{"s" if _deposit_state["weeks"] > 1 else ""})</div>',
                sanitize=False,
            )
        for msg in _alert_msgs:
            ui.html(f'<div class="banner banner-warning">\U0001f514 {msg}</div>', sanitize=False)

    banner_area()

    async def _finish_processing():
        try:
            loop = asyncio.get_event_loop()
            p = await loop.run_in_executor(_executor, _process_dividends, email, profile)
            deposit_amt, deposit_weeks = await loop.run_in_executor(
                _executor, _process_weekly, email, p
            )
            p = await loop.run_in_executor(_executor, _process_settlement, email, p)
            await loop.run_in_executor(_executor, _save, email, p)
            triggered = await loop.run_in_executor(_executor, _check_alerts, p)
            _alert_msgs[:] = triggered
            if deposit_amt:
                _deposit_state["amt"] = deposit_amt
                _deposit_state["weeks"] = deposit_weeks
                _audit("DEPOSIT", email, {"amount_cents": deposit_amt, "weeks": deposit_weeks})
            banner_area.refresh()
        except Exception as e:
            logger.error(f"Finish processing error: {e}", exc_info=True)

    ui.timer(0, _finish_processing, once=True)

    # ── Macro Indicators ──
    _macro_state: dict = {"data": None}

    @ui.refreshable
    def macro_bar():
        d = _macro_state["data"]
        if d is None:
            ui.html(
                '<div class="psummary"><div class="metric-box">Loading macro data...</div></div>',
                sanitize=False,
            )
            return
        items = ""
        for label, val_key, color_key, sub in [
            ("VIX", "vix", "vix_color", "Market fear gauge (<15 calm, >25 panic)"),
            ("CPI", "cpi", "cpi_color", "Consumer inflation, year-over-year"),
            ("PPI", "ppi", "ppi_color", "Producer input costs, year-over-year"),
            ("PCE", "pce", "pce_color", "Fed's preferred inflation gauge, YoY"),
            ("DXY", "dxy", None, f"US Dollar vs majors ({d.get('dxy_chg', '')} 1mo)"),
        ]:
            val = d.get(val_key, "N/A")
            cls = f"text-{d.get(color_key)}" if color_key else ""
            items += f'<div class="metric-box"><div class="label">{label}</div><div class="value {cls}">{val}</div><div class="sub">{sub}</div></div>'
        ui.html(
            f'<div class="psummary" style="margin-top:0">{items}</div>', sanitize=False
        )

    macro_bar()

    async def _macro_worker():
        loop = asyncio.get_event_loop()
        _macro_state["data"] = await loop.run_in_executor(_executor, _fetch_macro)
        macro_bar.refresh()

    ui.timer(0.1, _macro_worker, once=True)
    ui.timer(300, lambda: _macro_worker(), once=True)

    # ── Tabs ──
    with ui.tabs() as tabs:
        tp = ui.tab("\U0001f4cb Portfolio")
        tt = ui.tab("\U0001fa99 Trade")
        tr = ui.tab("\U0001f52c Research")
        ta = ui.tab("\U0001f514 Alerts")
        if is_teacher(email):
            ts = ui.tab("\U0001f3c6 Standings")

    panels = ui.tab_panels(tabs).classes("page-container")

    # ── PORTFOLIO ──
    with panels:
        with ui.tab_panel(tp):
            _portfolio_state = {"data": None}

            @ui.refreshable
            def portfolio_content():
                p = _portfolio_state["data"]
                if p is None:
                    ui.label("Loading portfolio...").classes("text-muted text-sm")
                    return
                holdings = p["holdings"]

                labels, values, colors = [], [], []
                if p["cash"] >= 0:
                    labels.append("Cash")
                    values.append(p["cash"])
                    colors.append("#3b82f6")
                if p["unsettled"] > 0:
                    labels.append("Unsettled")
                    values.append(p["unsettled"])
                    colors.append("#f59e0b")

                intl_frac = {
                    "VWO": 1.0, "VEA": 1.0, "EFA": 1.0, "IEMG": 1.0,
                    "EEM": 1.0, "VXUS": 1.0, "FXI": 1.0, "EWJ": 1.0,
                    "EWG": 1.0, "EWY": 1.0, "EWZ": 1.0, "INDA": 1.0,
                    "KWEB": 1.0, "FLTW": 1.0,
                    "BABA": 1.0, "TSM": 1.0, "NIO": 1.0, "PDD": 1.0,
                    "SE": 1.0, "SONY": 1.0, "TM": 1.0, "BP": 1.0,
                    "NVS": 1.0, "UL": 1.0, "AZN": 1.0, "DEO": 1.0,
                    "NVO": 1.0, "ADDYY": 1.0, "FRCOY": 1.0, "ASML": 1.0,
                    "ARM": 1.0,
                    "DRAM": 0.49, "BOTZ": 0.45, "TAN": 0.29,
                    "CHPS": 0.28, "IBB": 0.27, "AIQ": 0.20, "SOXQ": 0.21,
                    "IXJ": 0.19, "SMH": 0.16, "SOXX": 0.16, "ARKK": 0.12,
                    "ICLN": 0.21, "ARKQ": 0.10,
                }
                prices = p.get("prices", {})
                us_val = itnl_val = 0.0
                for t, pos in list(holdings.items()):
                    pr = prices.get(t)
                    if pr is not None:
                        mv = pos["shares"] * pr
                        frac = intl_frac.get(t.upper(), 0.0)
                        itnl_val += mv * frac
                        us_val += mv * (1 - frac)
                if us_val > 0:
                    labels.append("US")
                    values.append(us_val)
                    colors.append("#10b981")
                if itnl_val > 0:
                    labels.append("International")
                    values.append(itnl_val)
                    colors.append("#8b5cf6")

                sl, sv, sc = [], [], []
                palette = [
                    "#3b82f6",
                    "#f59e0b",
                    "#10b981",
                    "#8b5cf6",
                    "#f43f5e",
                    "#6366f1",
                    "#ec4899",
                    "#14b8a6",
                    "#f97316",
                    "#06b6d4",
                ]
                for i, t in enumerate(holdings):
                    pr = prices.get(t)
                    if pr is not None:
                        sv.append(holdings[t]["shares"] * pr)
                        sl.append(t)
                        sc.append(palette[i % len(palette)])

                if labels or sl:
                    with ui.row().classes("w-full gap-4"):
                        if labels:
                            fig = go.Figure(
                                data=[
                                    go.Pie(
                                        labels=labels,
                                        values=values,
                                        hole=0.4,
                                        marker=dict(
                                            colors=colors,
                                            line=dict(color="white", width=2),
                                        ),
                                        textinfo="percent",
                                        textposition="auto",
                                        textfont=dict(size=10),
                                    )
                                ]
                            )
                            fig.update_layout(
                                height=280,
                                margin=dict(l=0, r=0, t=20, b=50),
                                showlegend=True,
                                paper_bgcolor="rgba(0,0,0,0)",
                                legend=dict(
                                    orientation="h",
                                    yanchor="bottom",
                                    y=-0.3,
                                    xanchor="center",
                                    x=0.5,
                                ),
                            )
                            with ui.column().classes("chart-container"):
                                ui.plotly(fig).style("width: 100%; height: 280px")
                        if sl:
                            fig = go.Figure(
                                data=[
                                    go.Pie(
                                        labels=sl,
                                        values=sv,
                                        hole=0.4,
                                        marker=dict(
                                            colors=sc, line=dict(color="white", width=2)
                                        ),
                                        textinfo="percent",
                                        textposition="auto",
                                        textfont=dict(size=10),
                                    )
                                ]
                            )
                            fig.update_layout(
                                height=280,
                                margin=dict(l=0, r=0, t=20, b=50),
                                showlegend=True,
                                paper_bgcolor="rgba(0,0,0,0)",
                                legend=dict(
                                    orientation="h",
                                    yanchor="bottom",
                                    y=-0.3,
                                    xanchor="center",
                                    x=0.5,
                                ),
                            )
                            with ui.column().classes("chart-container"):
                                ui.plotly(fig).style("width: 100%; height: 280px")

                with ui.card().classes("w-full mt-4"):
                    ui.label("Positions").classes("font-bold text-lg mb-2")
                    if p["live_data"]:
                        df = pd.DataFrame(p["live_data"])
                        df["Return"] = df["Return"].map("{:+.2f}%".format)
                        t = (
                            ui.table.from_pandas(df)
                            .classes("w-full")
                            .props("hide-bottom")
                        )
                        t.add_slot(
                            "body-cell-Value",
                            """
                            <td style="text-align:right;vertical-align:middle">
                                {{ props.row.Value }}
                            </td>
                        """,
                        )
                        t.add_slot(
                            "body-cell-Return",
                            """
                            <td style="vertical-align:middle" :class="props.row.Return && props.row.Return.startsWith('-') ? 'text-negative font-semibold text-right' : 'text-positive font-semibold text-right'">
                                {{ props.row.Return }}
                            </td>
                        """,
                        )
                    else:
                        ui.label("No open positions.").classes("text-muted")

                if p["history"]:
                    with ui.card().classes("w-full mt-4"):
                        ui.label("Trade History").classes("font-bold text-lg mb-2")
                        df = pd.DataFrame(reversed(p["history"]))
                        cols = [
                            "time",
                            "type",
                            "ticker",
                            "shares",
                            "price",
                            "total",
                            "cost_basis",
                            "tax",
                        ]
                        for c in cols:
                            if c not in df.columns:
                                df[c] = ""
                        ui.table.from_pandas(df[cols]).classes("w-full").props(
                            "hide-bottom"
                        )

            async def _load_portfolio():
                loop = asyncio.get_event_loop()
                try:
                    _portfolio_state["data"] = await loop.run_in_executor(
                        _executor, _portfolio, profile
                    )
                except Exception as e:
                    logger.error(f"Portfolio load failed: {e}")
                    _portfolio_state["data"] = None
                portfolio_content.refresh()

            portfolio_content()

        # ── TRADE ──
        with ui.tab_panel(tt):
            pending = {"data": None}
            _sel_price_state = {"ticker": None, "price": None}
            opts = {t: format_ticker_option(t) for t in ALL_TICKERS}
            sel = (
                ui.select(options=opts, label="Search symbol", clearable=True)
                .classes("w-full")
                .props("use-input input-debounce=300 virtual-scroll virtual-scroll-item-size=36")
            )
            price_val = ui.label().classes("text-xl font-bold")
            price_sub = ui.html(sanitize=False).classes("text-sm text-muted")
            action = (
                ui.radio(["Buy", "Sell"], value="Buy")
                .props("inline dense")
                .classes("mt-1")
            )

            def _on_action_change():
                if action.value == "Sell":
                    owned = {
                        t: format_ticker_option(t) for t in profile.get("holdings", {})
                    }
                    sel.options = owned or {"": "— No positions —"}
                    sel.label = "Your holdings"
                else:
                    sel.options = opts
                    sel.label = "Search symbol"
                sel.value = None
                position_info.set_text("")
                limit_warn.set_text("")
                tax_info.set_text("")

            action.on_value_change(_on_action_change)
            mode = ui.radio(["Shares", "Amount ($)"], value="Shares").props(
                "inline dense"
            )
            shares_in = ui.number(
                label="Shares", value=1.0, min=0.001, step=0.1, format="%.4f"
            ).classes("w-full")
            amount_in = ui.number(
                label="Amount ($)", value=100.0, min=1.0, step=10.0
            ).classes("w-full")
            amount_in.set_visibility(False)
            preview = ui.label().classes("text-sm text-muted mt-1")
            position_info = ui.label().classes("text-sm text-muted mt-1")
            limit_warn = ui.label().classes("text-sm text-negative mt-1")
            tax_info = ui.label().classes("text-sm text-muted mt-1")

            async def _on_sel_change():
                t = sel.value
                _sel_price_state["ticker"] = t
                _sel_price_state["price"] = None
                pr = None
                if t:
                    loop = asyncio.get_event_loop()
                    pr, _, company = await loop.run_in_executor(_executor, lambda: fetch_stock_market_data(t))
                    _sel_price_state["price"] = pr
                    if pr is not None:
                        price_val.set_text(f"${pr:.2f}")
                        src = get_price_source(t)
                        src_html = (
                            ' <span style="color:#ef4444">\u25cf Live</span>'
                            if src == "live"
                            else ("  (prior close)" if src == "close" else "")
                        )
                        price_sub.set_content(f"{company}{src_html}")
                    else:
                        price_val.set_text("Price unavailable")
                        price_sub.set_content("")
                else:
                    price_val.set_text("")
                    price_sub.set_content("")
                if action.value == "Sell" and t and t in profile.get("holdings", {}):
                    pos = profile["holdings"][t]
                    sh = pos["shares"]
                    cb_total = pos["total_cost"] / 100.0
                    mv = sh * pr if pr else 0
                    position_info.set_text(
                        f"\U0001f4e6 Position: {sh:.4f} shares \u00b7 Cost basis: ${cb_total:,.2f} \u00b7 Market value: ${mv:,.2f}"
                    )
                else:
                    position_info.set_text("")
                tax_info.set_text("")
                if not t:
                    preview.set_text("")
                    limit_warn.set_text("")
                    return
                if pr is None:
                    preview.set_text("")
                    limit_warn.set_text("")
                    return
                cost = (
                    (shares_in.value * pr)
                    if mode.value == "Shares"
                    else amount_in.value
                )
                cost_c = _cents(cost)
                c_pct = (cost_c / profile["cash"]) * 100 if profile["cash"] > 0 else 0
                p = await loop.run_in_executor(_executor, lambda: _portfolio(profile))
                warn = ""
                if action.value == "Buy":
                    ex = profile["holdings"].get(t, {}).get("shares", 0)
                    w = ((cost + (ex * pr)) / p["total"]) * 100 if p["total"] > 0 else 0
                    preview.set_text(
                        f"\u2248 ${cost:,.2f}  \u00b7  {c_pct:.1f}% of cash  \u00b7  est. weight {w:.1f}%"
                    )
                    if cost_c > profile["cash"]:
                        warn = f'\u26a0 Insufficient cash ({_fmt(profile["cash"])} available, {_fmt(cost_c)} needed)'
                    tax_info.set_text("")
                else:
                    if t in profile["holdings"]:
                        o = profile["holdings"][t]["shares"]
                        sh_selling = (
                            shares_in.value if mode.value == "Shares" else cost / pr
                        )
                        preview.set_text(f"\u2248 {sh_selling:.4f} shares")
                        if sh_selling > o + 0.0001:
                            warn = f"\u26a0 Only {o:.4f} shares owned"
                        frac = sh_selling / o
                        cb_d = (frac * profile["holdings"][t]["total_cost"]) / 100.0
                        profit_d = cost - cb_d
                        tax_d = max(0, profit_d * 0.15)
                        net_d = cost - tax_d
                        tax_info.set_text(
                            f"Cost basis: ${cb_d:.2f}  \u00b7  Profit: ${profit_d:.2f}\nTax (15%): ${tax_d:.2f}  \u2192  Net proceeds: ${net_d:.2f} (unsettled)"
                        )
                    else:
                        preview.set_text("")
                        tax_info.set_text("")
                limit_warn.set_text(warn)

            async def _upd_preview():
                t = sel.value
                if not t:
                    preview.set_text("")
                    limit_warn.set_text("")
                    return
                pr = _sel_price_state["price"] if _sel_price_state["ticker"] == t else None
                if pr is None:
                    loop = asyncio.get_event_loop()
                    fetched, _, _ = await loop.run_in_executor(_executor, lambda: fetch_stock_market_data(t))
                    if fetched is not None:
                        _sel_price_state["ticker"] = t
                        _sel_price_state["price"] = fetched
                        pr = fetched
                if pr is None:
                    preview.set_text("")
                    limit_warn.set_text("")
                    return
                cost = (
                    (shares_in.value * pr)
                    if mode.value == "Shares"
                    else amount_in.value
                )
                cost_c = _cents(cost)
                c_pct = (cost_c / profile["cash"]) * 100 if profile["cash"] > 0 else 0
                p = await loop.run_in_executor(_executor, lambda: _portfolio(profile))
                warn = ""
                if action.value == "Buy":
                    ex = profile["holdings"].get(t, {}).get("shares", 0)
                    w = ((cost + (ex * pr)) / p["total"]) * 100 if p["total"] > 0 else 0
                    preview.set_text(
                        f"\u2248 ${cost:,.2f}  \u00b7  {c_pct:.1f}% of cash  \u00b7  est. weight {w:.1f}%"
                    )
                    if cost_c > profile["cash"]:
                        warn = f'\u26a0 Insufficient cash ({_fmt(profile["cash"])} available, {_fmt(cost_c)} needed)'
                    tax_info.set_text("")
                else:
                    if t in profile["holdings"]:
                        o = profile["holdings"][t]["shares"]
                        sh_selling = (
                            shares_in.value if mode.value == "Shares" else cost / pr
                        )
                        preview.set_text(f"\u2248 {sh_selling:.4f} shares")
                        if sh_selling > o + 0.0001:
                            warn = f"\u26a0 Only {o:.4f} shares owned"
                        frac = sh_selling / o
                        cb_d = (frac * profile["holdings"][t]["total_cost"]) / 100.0
                        profit_d = cost - cb_d
                        tax_d = max(0, profit_d * 0.15)
                        net_d = cost - tax_d
                        tax_info.set_text(
                            f"Cost basis: ${cb_d:.2f}  \u00b7  Profit: ${profit_d:.2f}\nTax (15%): ${tax_d:.2f}  \u2192  Net proceeds: ${net_d:.2f} (unsettled)"
                        )
                    else:
                        preview.set_text("")
                        tax_info.set_text("")
                limit_warn.set_text(warn)

            def _upd_mode():
                s = mode.value == "Shares"
                shares_in.set_visibility(s)
                amount_in.set_visibility(not s)

            sel.on_value_change(lambda: _on_sel_change())
            action.on_value_change(lambda: _upd_preview())
            mode.on_value_change(lambda: _upd_preview())
            mode.on_value_change(lambda: _upd_mode())
            shares_in.on_value_change(lambda: _upd_preview())
            amount_in.on_value_change(lambda: _upd_preview())

            @ui.refreshable
            def confirm_card():
                d = pending["data"]
                if not d:
                    return
                with ui.card().classes("w-full bg-blue-50 border-2 border-blue-200"):
                    ui.label(
                        f"Confirm {d['action']}: {d['shares']:.4f} shares of {d['ticker']} at ${d['price']:.2f} = ${d['cost']:.2f}"
                    ).classes("font-semibold text-blue-900")
                    if d["action"] == "Sell" and d["ticker"] in profile.get(
                        "holdings", {}
                    ):
                        o = profile["holdings"][d["ticker"]]["shares"]
                        _frac = d["shares"] / o
                        _cb = (
                            _frac * profile["holdings"][d["ticker"]]["total_cost"]
                        ) / 100.0
                        _profit = d["cost"] - _cb
                        _tax = max(0, _profit * 0.15)
                        _net = d["cost"] - _tax
                        ui.label(
                            f"Cost basis: ${_cb:.2f}  \u00b7  Profit: ${_profit:.2f}  \u00b7  Tax (15%): ${_tax:.2f}  \u2192  Net: ${_net:.2f}"
                        ).classes("text-sm text-muted")
                    with ui.row().classes("gap-3 mt-3"):
                        ui.button(
                            f"\u2705 Confirm {d['action']}", on_click=lambda: _exec(d)
                        ).props("color=primary")
                        ui.button(
                            "\u274c Cancel",
                            on_click=lambda: (
                                pending.update({"data": None}),
                                confirm_card.refresh(),
                            ),
                        )

            async def _exec(data):
                loop = asyncio.get_event_loop()
                success, error, event, details = await loop.run_in_executor(_executor, lambda: _execute_trade(data, profile, email, _profile_locks, _save, ALL_TICKERS))
                if not success:
                    ui.notify(error, type="negative")
                    if "Price changed" in error or "re-review" in error:
                        pending["data"] = None
                        confirm_card.refresh()
                    return
                _touch_session()
                _audit(event, email, details)
                _summary_state["data"] = await loop.run_in_executor(_executor, lambda: _portfolio(profile))
                _portfolio_state["data"] = _summary_state["data"]
                pending["data"] = None
                confirm_card.refresh()
                summary.refresh()
                portfolio_content.refresh()
                try:
                    positions_info.refresh()
                except Exception:
                    pass
                try:
                    movers.refresh()
                except Exception:
                    pass
                try:
                    standings_content.refresh()
                except Exception:
                    pass
                ui.notify("\u2705 Trade executed!", type="positive")

            async def _review():
                loop = asyncio.get_event_loop()
                pr, _, _ = await loop.run_in_executor(_executor, lambda: fetch_stock_market_data(sel.value))
                valid, err, data = _validate_trade_inputs(sel.value, pr, action.value, mode.value, shares_in.value, amount_in.value, profile, ALL_TICKERS)
                if not valid:
                    ui.notify(err, type="negative")
                    return
                pending["data"] = data
                confirm_card.refresh()

            with ui.row().classes("w-full gap-4"):
                with ui.card().classes("trade-ticket"):
                    ui.label("Trade Ticket").classes("font-bold text-lg mb-3")
                    sel
                    with ui.row().classes("items-baseline gap-2 mt-1"):
                        price_val
                        price_sub
                    action
                    mode
                    shares_in
                    amount_in
                    preview
                    ui.button("\U0001f4cb Review Order", on_click=_review).props(
                        "color=primary"
                    ).classes("w-full mt-2")
                    confirm_card()

                with ui.card().classes("market-movers"):
                    ui.label("\U0001f4c8 Your Positions").classes(
                        "font-bold text-lg mb-3"
                    )
                    ui.label("Click a position to sell it.").classes(
                        "text-muted text-xs mb-2"
                    )

                    def _sell_prefill(ticker: str, shares: float):
                        action.set_value("Sell")
                        _on_action_change()
                        sel.set_value(ticker)
                        mode.set_value("Shares")
                        shares_in.set_value(shares)
                        ui.notify(
                            f"Selling {ticker} ({shares:g} shares) - review and confirm.",
                            type="info",
                        )

                    @ui.refreshable
                    def positions_info():
                        p = _summary_state["data"]
                        if p is None:
                            ui.label("Loading positions...").classes(
                                "text-muted text-sm"
                            )
                            return
                        live = p.get("live_data", [])
                        if not live:
                            ui.label("No open positions.").classes(
                                "text-muted text-sm"
                            )
                            return
                        for row in live:
                            tick = row["Ticker"]
                            ret = row["Return"]
                            ret_cls = (
                                "text-positive" if ret >= 0 else "text-negative"
                            )
                            with ui.row().classes(
                                "w-full items-center justify-between bg-gray-50 rounded-lg px-3 py-1.5 cursor-pointer hover:bg-blue-50"
                            ).on(
                                "click",
                                lambda t=tick, sh=row["Shares"]: _sell_prefill(t, sh),
                            ):
                                ui.label(tick).classes("text-xs font-bold w-14")
                                ui.label(
                                    f"{row['Shares']:g} sh @ {row['Avg Price']}"
                                ).classes(
                                    "text-xs text-muted flex-1 truncate"
                                )
                                ui.label(row["Live Price"]).classes(
                                    "text-xs w-16 text-right"
                                )
                                ui.label(row["Value"]).classes(
                                    "text-xs w-20 text-right font-semibold"
                                )
                                ui.label(f"{ret:+.2f}%").classes(
                                    f"text-xs font-semibold w-16 text-right {ret_cls}"
                                )

                    positions_info()

        # ── RESEARCH ──
        with ui.tab_panel(tr):
            with ui.row().classes("w-full gap-4"):
                with ui.card().classes("research-vol"):
                    ui.label("Volatility Calculator").classes("font-bold text-lg mb-3")
                    vs = (
                        ui.select(options=opts, label="Search symbol", clearable=True)
                        .classes("w-full")
                        .props("use-input input-debounce=300 virtual-scroll virtual-scroll-item-size=36")
                    )
                    vp = ui.select(
                        options=CHART_PERIODS, value="3mo", label="Period"
                    ).classes("w-full")
                    v_std = ui.label("\u2014").classes("text-2xl font-bold")
                    v_range = ui.label("\u2014").classes("text-2xl font-bold")
                    v_desc = ui.label("Pick a stock to calculate volatility.").classes(
                        "text-sm text-muted mt-2"
                    )

                    async def _vol_worker(t, period):
                        try:
                            loop = asyncio.get_event_loop()
                            d = await loop.run_in_executor(
                                _executor,
                                lambda: _flatten_cols(
                                    yf.download(
                                        t, period=period, progress=False, timeout=20
                                    )
                                ),
                            )
                            logger.info(
                                f"Volatility: downloaded {len(d) if d is not None else 0} rows for {t}"
                            )
                            if d is None or len(d) < 2:
                                v_std.set_text("N/A")
                                v_range.set_text("N/A")
                                v_desc.set_text("Not enough data.")
                                return
                            d["chg"] = d["Close"].pct_change() * 100
                            std = d[["Close", "chg"]].dropna()["chg"].std()
                            pl = CHART_PERIODS.get(period, period).lower()
                            risk = (
                                "very low"
                                if std < 0.5
                                else (
                                    "low"
                                    if std < 1.0
                                    else (
                                        "moderate"
                                        if std < 1.5
                                        else "high" if std < 2.5 else "very high"
                                    )
                                )
                            )
                            v_std.set_text(f"{std:.2f}%")
                            v_range.set_text(f"\u00b1{std:.2f}%")
                            v_desc.set_text(
                                f"Over {pl}, {t} typically moves \u00b1{std:.1f}% per day. Risk: {risk}."
                            )
                            logger.info(
                                f"Volatility: std={std:.2f}%, risk={risk} for {t}"
                            )
                        except Exception as e:
                            logger.error(
                                f"Volatility calc error for {t}: {e}", exc_info=True
                            )
                            v_std.set_text("N/A")
                            v_range.set_text("N/A")
                            v_desc.set_text("Error fetching data.")

                    def _vol():
                        t = vs.value
                        if not t:
                            v_std.set_text("\u2014")
                            v_range.set_text("\u2014")
                            v_desc.set_text("Pick a stock.")
                            return
                        if t not in ALL_TICKERS:
                            v_desc.set_text("Invalid ticker.")
                            return
                        p = vp.value
                        ui.timer(0, lambda t=t, p=p: _vol_worker(t, p), once=True)

                    vs.on_value_change(lambda: _vol())
                    vp.on_value_change(lambda: _vol())

                    with ui.row().classes("w-full gap-2 mt-2"):
                        with ui.column().classes("flex-1 bg-gray-50 rounded-lg p-3"):
                            ui.label("Daily Volatility").classes(
                                "text-xs text-muted uppercase tracking-wider font-medium"
                            )
                            v_std
                        with ui.column().classes("flex-1 bg-gray-50 rounded-lg p-3"):
                            ui.label("Typical Range").classes(
                                "text-xs text-muted uppercase tracking-wider font-medium"
                            )
                            v_range
                    v_desc

                with ui.card().classes("research-chart"):
                    ui.label("Price History").classes("font-bold text-lg mb-3")
                    with ui.row().classes("gap-2"):
                        cp_sel = ui.select(
                            options=CHART_PERIODS, value="3mo", label="Period"
                        ).classes("w-40")
                        cs_sel = ui.select(
                            options={"Line": "Line", "Candlestick": "Candlestick"},
                            value="Line",
                            label="Style",
                        ).classes("w-36")
                    chart_price = ui.label().classes("text-3xl font-bold")
                    chart_sub = ui.label().classes("text-sm text-muted")
                    ui.html(
                        '<div id="tvchart" style="width:100%;height:380px;min-height:400px;position:relative;overflow:hidden;box-sizing:border-box"></div>',
                        sanitize=False,
                    )

                    async def _chart_worker(t, period, style):
                        try:
                            loop = asyncio.get_event_loop()
                            price_data, hist = await asyncio.gather(
                                loop.run_in_executor(_executor, fetch_stock_market_data, t),
                                loop.run_in_executor(_executor, fetch_full_history, t, period),
                            )
                            pr = price_data[0] if price_data else None
                            company = price_data[2] if price_data else ""
                            chart_price.set_text(f"${pr:.2f}" if pr else "")
                            chart_sub.set_text(company if pr else "")
                            if hist is None or len(hist) < 2:
                                logger.error(
                                    f"Chart: not enough history for {t} (period={period}, rows={len(hist) if hist is not None else 'None'})"
                                )
                                ui.run_javascript(
                                    """
(function() {
    var maxW = Date.now() + 5000, poll = function() {
        if (window.__tv && window.__tv.ready) {
            window.__tv.candle.setData([]); window.__tv.line.setData([]);
        } else if (Date.now() < maxW) { setTimeout(poll, 200); }
    }; poll();
})();
                                    """
                                )
                                return
                            logger.info(
                                f"Chart: loaded {len(hist)} rows for {t} ({period})"
                            )
                            data = []
                            for idx, row in hist.iterrows():
                                data.append(
                                    {
                                        "time": idx.strftime('%Y-%m-%d'),
                                        "open": float(row["Open"]),
                                        "high": float(row["High"]),
                                        "low": float(row["Low"]),
                                        "close": float(row["Close"]),
                                    }
                                )
                            line_data = [
                                {"time": d["time"], "value": d["close"]} for d in data
                            ]
                            candle_vis = "true" if style == "Candlestick" else "false"
                            line_vis = "true" if style == "Line" else "false"
                            ui.run_javascript(
                                f"""
(function() {{
    var maxWait = Date.now() + 10000, poll = function() {{
        if (window.__tv && window.__tv.ready) {{
            var tvEl = document.getElementById('tvchart');
            if (tvEl && tvEl.clientWidth > 0) {{ window.__tv.chart.resize(tvEl.clientWidth, tvEl.clientHeight); }}
            window.__tv.candle.setData({json.dumps(data)});
            window.__tv.line.setData({json.dumps(line_data)});
            window.__tv.candle.applyOptions({{visible: {candle_vis}}});
            window.__tv.line.applyOptions({{visible: {line_vis}}});
            window.__tv.chart.timeScale().fitContent();
        }} else if (Date.now() < maxWait) {{
            setTimeout(poll, 200);
        }} else {{
            console.error('Chart init timeout — __tv not ready');
        }}
    }};
    poll();
}})();
                            """
                            )
                            logger.info(
                                f"Chart: rendered {len(data)} candles for {t} ({style})"
                            )
                        except Exception as e:
                            logger.error(f"Chart error for {t}: {e}", exc_info=True)

                    def _chart():
                        t = vs.value
                        if not t:
                            chart_price.set_text("")
                            chart_sub.set_text("")
                            return
                        if t not in ALL_TICKERS:
                            chart_price.set_text("")
                            chart_sub.set_text("")
                            return
                        p = cp_sel.value
                        s = cs_sel.value
                        ui.timer(
                            0, lambda t=t, p=p, s=s: _chart_worker(t, p, s), once=True
                        )

                    cp_sel.on_value_change(lambda: _chart())
                    cs_sel.on_value_change(lambda: _chart())
                    vs.on_value_change(lambda: _chart())

            # ══ Research: Market Movers ══
            with ui.card().classes("w-full"):
                ui.label("\U0001f4ca Market Movers").classes(
                    "font-bold text-lg mb-3"
                )

                async def _load_movers():
                    import asyncio as _asyncio
                    import time as _time
                    now = _time.time()
                    action = movers_load_action(_movers_cache, now, _MOVERS_TTL)
                    if action == "refresh":
                        movers.refresh()
                        return
                    if action == "wait":
                        deadline = now + 20
                        while _movers_cache["loading"] and _time.time() < deadline:
                            await _asyncio.sleep(0.25)
                        if _movers_cache["loaded"]:
                            movers.refresh()
                        return
                    _movers_cache["loading"] = True
                    try:
                        def _fetch():
                            all_data = []
                            stock_groups = [
                                STOCK_TICKERS[i : i + 100]
                                for i in range(0, len(STOCK_TICKERS), 100)
                            ]
                            for group in stock_groups + [ETF_TICKERS]:
                                try:
                                    all_data.extend(list(get_top_movers(tuple(group))))
                                except Exception as e:
                                    logger.error(
                                        f"Movers batch error ({len(group)} tickers): {e}"
                                    )
                            return all_data

                        loop = asyncio.get_event_loop()
                        _movers_cache["data"] = await loop.run_in_executor(_executor, _fetch)
                        _movers_cache["loaded"] = True
                        _movers_cache["ts"] = _time.time()
                        movers.refresh()
                    finally:
                        _movers_cache["loading"] = False

                @ui.refreshable
                def movers():
                    if not _movers_cache["loaded"]:
                        ui.label("Loading market data...").classes(
                            "text-muted text-sm"
                        )
                    else:
                        for label, items in [
                            (
                                "Stocks",
                                [
                                    x
                                    for x in _movers_cache["data"]
                                    if x[0] in STOCK_TICKERS
                                ],
                            ),
                            (
                                "ETFs",
                                [
                                    x
                                    for x in _movers_cache["data"]
                                    if x[0] in ETF_TICKERS
                                ],
                            ),
                        ]:
                            gainers = [x for x in items if x[3] > 0][:5]
                            losers = [x for x in items if x[3] < 0][-5:][::-1]
                            if not gainers and not losers:
                                ui.label(f"{label}: No data").classes(
                                    "text-muted text-xs"
                                )
                                continue
                            with ui.column().classes("w-full gap-1 mb-3"):
                                if gainers:
                                    ui.label(f"{label} \u2191").classes(
                                        "text-xs font-semibold text-positive"
                                    )
                                    for tick, n, p, c in gainers:
                                        with ui.row().classes(
                                            "w-full items-center justify-between bg-green-50 rounded-lg px-3 py-1.5"
                                        ):
                                            ui.label(tick).classes(
                                                "text-xs font-bold w-14"
                                            )
                                            ui.label(n[:18]).classes(
                                                "text-xs text-muted flex-1 truncate"
                                            )
                                            ui.label(f"${p:.2f}").classes(
                                                "text-xs w-16 text-right"
                                            )
                                            ui.label(f"{c:+.2f}%").classes(
                                                "text-xs font-semibold w-16 text-right text-positive"
                                            )
                                if losers:
                                    ui.label(f"{label} \u2193").classes(
                                        "text-xs font-semibold text-negative mt-1"
                                    )
                                    for tick, n, p, c in losers:
                                        with ui.row().classes(
                                            "w-full items-center justify-between bg-red-50 rounded-lg px-3 py-1.5"
                                        ):
                                            ui.label(tick).classes(
                                                "text-xs font-bold w-14"
                                            )
                                            ui.label(n[:18]).classes(
                                                "text-xs text-muted flex-1 truncate"
                                            )
                                            ui.label(f"${p:.2f}").classes(
                                                "text-xs w-16 text-right"
                                            )
                                            ui.label(f"{c:+.2f}%").classes(
                                                "text-xs font-semibold w-16 text-right text-negative"
                                            )
                                ui.separator().classes("my-1")

                movers()

            # ══ Research: News ══
            ui.separator().classes("mt-4")
            with ui.card().classes("w-full"):
                ui.label("\U0001f4f0 Market News").classes("font-bold text-lg mb-3")
                _news_container = ui.label()
                _news_state: dict = {"ticker": None}
                _pending_news_url: list[str] = [""]

                with ui.dialog() as _news_link_dialog, ui.card():
                    ui.label("Leaving Simulator").classes("text-lg font-bold")
                    ui.label(
                        "You are opening a link to an external financial news website. "
                        "External websites are outside our control and may contain ads, "
                        "tracking, or unmoderated content. Please proceed with caution."
                    ).classes("text-sm text-muted mt-1")
                    _news_link_url = ui.label("").classes(
                        "text-xs text-gray-500 break-all mt-2"
                    )
                    with ui.row().classes("gap-2 mt-4 justify-end"):
                        ui.button("Cancel", on_click=_news_link_dialog.close).props(
                            "flat"
                        )
                        ui.button(
                            "Proceed",
                            on_click=lambda: [
                                ui.navigate.to(
                                    _pending_news_url[0], new_tab=True
                                ),
                                _news_link_dialog.close(),
                            ],
                        ).props("color=primary")

                def _open_news_link(headline: str, url: str):
                    _pending_news_url[0] = url
                    _news_link_url.set_text(url)
                    _news_link_dialog.open()

                async def _news_worker(t):
                    try:
                        loop = asyncio.get_event_loop()
                        raw = await loop.run_in_executor(
                            _executor, lambda: yf.Ticker(t).news
                        )
                        articles = []
                        for a in (raw or []):
                            c = a.get("content") or {}
                            source = (c.get("provider") or {}).get("displayName", "")
                            if source in NEWS_WHITELIST:
                                articles.append(a)
                        articles = articles[:5]
                        _news_state["articles"] = articles
                        _news_state["ticker"] = t
                        _news_container.set_text("")
                        _news_container.clear()
                        if not articles:
                            with _news_container:
                                ui.label("No recent news.").classes(
                                    "text-muted text-sm"
                                )
                            return
                        with _news_container:
                            for a in articles[:5]:
                                c = a.get("content") or {}
                                ts = c.get("pubDate", 0)
                                headline = html.escape(c.get("title", ""))
                                url = (
                                    (c.get("clickThroughUrl") or {}).get("url", "")
                                    or (c.get("canonicalUrl") or {}).get("url", "")
                                )
                                source = html.escape(
                                    (c.get("provider") or {}).get(
                                        "displayName", ""
                                    )
                                )
                                summary = html.escape(c.get("summary", ""))
                                with ui.card().classes("w-full q-pa-sm q-mb-sm"):
                                    with ui.row().classes("items-start gap-2"):
                                        ui.label(headline).classes(
                                            "font-semibold text-sm text-blue-600 cursor-pointer underline"
                                        ).on(
                                            "click",
                                            lambda url=url, headline=headline: _open_news_link(
                                                headline, url
                                            ),
                                        )
                                        ui.label(
                                            f"— {source} \u00b7 {_relative_time(ts)}"
                                        ).classes("text-xs text-muted")
                                    if summary:
                                        ui.label(summary).classes(
                                            "text-xs text-gray-600 line-clamp-2"
                                        )
                    except Exception as e:
                        logger.error(f"News error for {t}: {e}", exc_info=True)
                        _news_container.set_text(f"Error loading news: {e}")

                def _load_news():
                    t = vs.value
                    if not t:
                        _news_container.set_text("Select a stock to view news.")
                        return
                    if t not in ALL_TICKERS:
                        _news_container.set_text("Invalid ticker.")
                        return
                    current_settings = load_class_settings()
                    if not current_settings.get("news_enabled", True):
                        _news_container.set_text(
                            "Market news is currently disabled by your instructor."
                        )
                        return
                    _news_container.set_text("Loading news...")
                    ui.timer(0, lambda t=t: _news_worker(t), once=True)

                vs.on_value_change(lambda: _load_news())

                def _on_tab_change(e):
                    if e.value == "\U0001f52c Research":
                        try:
                            _load_movers()
                        except Exception:
                            logger.debug("movers load on Research tab open failed")
                        ui.run_javascript("""
                            var el = document.getElementById('tvchart');
                            if (!el) return;
                            if (window.__tv && window.__tv.ready) {
                                var w = el.clientWidth, h = el.clientHeight;
                                if (w > 0 && h > 0) { window.__tv.chart.resize(w, h); }
                                window.__tv.chart.timeScale().fitContent();
                            } else {
                                (function initTv() {
                                    if (!initTv._max) { initTv._max = Date.now() + 10000; }
                                    if (Date.now() > initTv._max) { console.error('Chart init timeout'); return; }
                                    try {
                                        if (typeof LightweightCharts === 'undefined') { setTimeout(initTv, 200); return; }
                                        var iw = el.clientWidth || 800, ih = el.clientHeight || 380;
                                        var c = LightweightCharts.createChart(el, {
                                            width: iw, height: ih,
                                            layout: { textColor: '#1f2937', fontFamily: "'Inter',-apple-system,sans-serif", fontSize: 12 },
                                            grid: { vertLines: { color: 'rgba(128,128,128,0.1)' }, horzLines: { color: 'rgba(128,128,128,0.1)' } },
                                            timeScale: { borderColor: 'rgba(128,128,128,0.2)', timeVisible: false },
                                            rightPriceScale: { borderColor: 'rgba(128,128,128,0.2)' },
                                            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                                            handleScroll: false, handleScale: false,
                                        });
                                        window.__tv = { ready: true, chart: c };
                                        window.__tv.candle = c.addSeries(LightweightCharts.CandlestickSeries, {
                                            upColor: '#10b981', downColor: '#f43f5e',
                                            borderUpColor: '#10b981', borderDownColor: '#f43f5e',
                                            wickUpColor: '#10b981', wickDownColor: '#f43f5e',
                                            priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
                                        });
                                        window.__tv.line = c.addSeries(LightweightCharts.LineSeries, {
                                            color: '#3b82f6', lineWidth: 2,
                                            priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
                                        });
                                        if (window.ResizeObserver) {
                                            new ResizeObserver(function() {
                                                var w2 = el.clientWidth, h2 = el.clientHeight;
                                                if (w2 > 0 && h2 > 0) { c.resize(w2, h2); }
                                            }).observe(el);
                                        }
                                    } catch(e) { setTimeout(initTv, 200); }
                                })();
                            }
                        """)
                        if vs.value:
                            _chart()
                tabs.on_value_change(_on_tab_change)

        # ── ALERTS ──
        with ui.tab_panel(ta):
            with ui.card().classes("w-full"):
                ui.label("Price Alerts").classes("font-bold text-lg mb-2")
                ui.label("Notify when a stock crosses a target price.").classes(
                    "text-sm text-muted mb-3"
                )
                asel = (
                    ui.select(options=opts, label="Search symbol", clearable=True)
                    .classes("w-56")
                    .props("use-input input-debounce=300 virtual-scroll virtual-scroll-item-size=36")
                )
                adir = ui.select(
                    options={"above": "Above", "below": "Below"}, value="above"
                ).classes("w-32")
                apr = ui.number(
                    label="Target Price", value=200.0, min=0.01, step=1.0
                ).classes("w-32")

                @ui.refreshable
                def alert_list():
                    for i, a in enumerate(profile.get("alerts", [])):
                        with ui.row().classes(
                            "items-center gap-3 py-2 border-b border-gray-100"
                        ):
                            ui.label(a["ticker"]).classes("font-semibold w-20")
                            ui.label(f"\u2192 {a['direction']}").classes(
                                "text-muted w-20 text-sm"
                            )
                            ui.label(f"${a['price']:.2f}").classes("w-20 text-sm")
                            ui.button("\u2715", on_click=lambda idx=i: _del(idx)).props(
                                "flat dense color=negative"
                            )

                def _add():
                    t = asel.value
                    if not t:
                        ui.notify("Select a ticker", type="warning")
                        return
                    if t not in ALL_TICKERS:
                        ui.notify("Invalid ticker.", type="negative")
                        return
                    _touch_session()
                    profile.setdefault("alerts", []).append(
                        {"ticker": t, "direction": adir.value, "price": apr.value}
                    )
                    _save(email, profile)
                    _audit("ALERT_CREATE", email, {"ticker": t, "direction": adir.value, "price": apr.value})
                    alert_list.refresh()
                    ui.notify("Alert added!", type="positive")

                def _del(idx):
                    alerts = profile.get("alerts", [])
                    if idx < len(alerts):
                        _touch_session()
                        popped = alerts.pop(idx)
                        _save(email, profile)
                        _audit("ALERT_DELETE", email, popped)
                        alert_list.refresh()

                with ui.row().classes("items-center gap-2"):
                    asel
                    adir
                    apr
                    ui.button("+ Add", on_click=_add).props("color=primary")
                alert_list()

        # ── STANDINGS ──
        _standings_state: dict = {"rows": None}
        if is_teacher(email):
            with ui.tab_panel(ts):
                with ui.card().classes("w-full"):
                    ui.label("\U0001f3c6 Classroom Standings").classes(
                        "font-bold text-lg mb-3"
                    )

                    async def _load_standings():
                        def _work():
                            db = get_gcs_database()
                            if not db:
                                return []
                            db.pop(_safe_email_key("rpiana@stjohnsguam.com"), None)
                            db.pop("rpiana@stjohnsguam.com", None)
                            all_tickers = set()
                            for p in db.values():
                                p = _migrate_profile(p)
                                _clean_dust_holdings(p)
                                all_tickers.update(p.get("holdings", {}).keys())
                            price_map = {}
                            if all_tickers:
                                tl = list(all_tickers)
                                futures = {t: _executor.submit(fetch_stock_market_data, t) for t in tl}
                                for t, fut in futures.items():
                                    try:
                                        pr = fut.result(timeout=10)[0]
                                        if pr is not None:
                                            price_map[t] = pr
                                    except Exception:
                                        pass
                            rows = []
                            for e, p in db.items():
                                p = _migrate_profile(p)
                                _clean_dust_holdings(p)
                                mv = 0.0
                                for t, pos in p.get("holdings", {}).items():
                                    pr = price_map.get(t)
                                    if pr is not None:
                                        mv += pos["shares"] * pr
                                cash = p.get("cash", STARTING_CASH_CENTS)
                                unsettled = p.get("unsettled_cash", 0)
                                nw = ((cash + unsettled) / 100) + mv
                                rows.append(
                                    {
                                        "Student": p.get("name", "Student"),
                                        "Net Worth": nw,
                                        "Return": (
                                            (nw - ((STARTING_CASH_CENTS + p.get("total_deposits", 0)) / 100))
                                            / ((STARTING_CASH_CENTS + p.get("total_deposits", 0)) / 100)
                                        )
                                        * 100,
                                    }
                                )
                            return rows
                        loop = asyncio.get_event_loop()
                        rows = await loop.run_in_executor(_executor, _work)
                        _standings_state["rows"] = rows
                        standings_content.refresh()

                    @ui.refreshable
                    def standings_content():
                        rows = _standings_state["rows"]
                        if rows is None:
                            ui.label("Loading standings...").classes(
                                "text-muted text-sm"
                            )
                            return
                        if not rows:
                            ui.label("No participants.").classes("text-muted")
                            return
                        df = (
                            pd.DataFrame(rows)
                            .sort_values("Net Worth", ascending=False)
                            .reset_index(drop=True)
                        )
                        df["Rank"] = df.index + 1
                        df["Net Worth"] = df["Net Worth"].map("${:,.2f}".format)
                        df["Return"] = df["Return"].map("{:+.2f}%".format)
                        ui.table.from_pandas(
                            df[["Rank", "Student", "Net Worth", "Return"]]
                        ).classes("w-full").props("hide-bottom")

                    standings_content()

    # ── Teacher admin ─────────────────────────────────────
    if is_teacher(email):
        with ui.card().classes(
            "w-full page-container p-4 mt-4 border-t-2 border-blue-200"
        ):
            ui.label("\U0001f468\u200d\U0001f3eb Teacher Administration").classes(
                "font-bold text-lg mb-2"
            )
            with ui.tabs().classes("w-full") as at:
                a1 = ui.tab("\U0001f4ca Class Portfolio Data")
                a2 = ui.tab("\U0001f9ea Sandbox")

            with ui.tab_panels(at):
                with ui.tab_panel(a1):
                    _admin_state: dict = {"rows": None}

                    _admin_settings = load_class_settings()

                    def _toggle_news(enabled: bool):
                        _admin_settings["news_enabled"] = enabled
                        save_class_settings(_admin_settings)
                        if enabled:
                            ui.notify("Market News enabled for students.", type="positive")
                        else:
                            ui.notify("Market News disabled for students.", type="warning")

                    with ui.card().classes("w-full q-mb-md"):
                        ui.label("\u2699\ufe0f Class Settings").classes(
                            "font-semibold text-sm mb-2"
                        )
                        ui.switch(
                            "Enable Market News section for students",
                            value=_admin_settings.get("news_enabled", True),
                            on_change=lambda e: _toggle_news(e.value),
                        ).classes("text-sm")

                    async def _load_admin():
                        def _work():
                            db = get_gcs_database()
                            if not db:
                                return []
                            db.pop(_safe_email_key("rpiana@stjohnsguam.com"), None)
                            db.pop("rpiana@stjohnsguam.com", None)
                            all_tickers = set()
                            for p in db.values():
                                p = _migrate_profile(p)
                                _clean_dust_holdings(p)
                                all_tickers.update(p.get("holdings", {}).keys())
                            price_map = {}
                            if all_tickers:
                                tl = list(all_tickers)
                                futures = {t: _executor.submit(fetch_stock_market_data, t) for t in tl}
                                for t, fut in futures.items():
                                    try:
                                        pr = fut.result(timeout=10)[0]
                                        if pr is not None:
                                            price_map[t] = pr
                                    except Exception:
                                        pass
                            _email_by_hash = {}
                            for ce, cp in _profiles.items():
                                if cp:
                                    _email_by_hash[_safe_email_key(ce)] = ce
                            rows = []
                            for e, p in db.items():
                                p = _migrate_profile(p)
                                _clean_dust_holdings(p)
                                if "email" not in p:
                                    p["email"] = _email_by_hash.get(e, "unknown")
                                mv = 0.0
                                holdings_detail = []
                                for t, pos in p.get("holdings", {}).items():
                                    pr = price_map.get(t)
                                    val = pos["shares"] * pr if pr else 0
                                    mv += val
                                    cb = pos["total_cost"] / 100.0
                                    holdings_detail.append({
                                        "ticker": t,
                                        "shares": pos["shares"],
                                        "cost_basis": cb,
                                        "price": pr,
                                        "value": val,
                                    })
                                cash = p.get("cash", STARTING_CASH_CENTS)
                                unsettled = p.get("unsettled_cash", 0)
                                nw = ((cash + unsettled) / 100) + mv
                                cap = (STARTING_CASH_CENTS + p.get("total_deposits", 0)) / 100
                                pl = nw - cap
                                rows.append(
                                    {
                                        "_key": e,
                                        "Student": p.get("name", "Unknown"),
                                        "Email": p.get("email") or "unknown",
                                        "Net Worth": nw,
                                        "P&L": pl,
                                        "Return": (pl / cap) * 100,
                                        "Cash": cash / 100,
                                        "Stock Value": mv,
                                        "Trades": len(p.get("history", [])),
                                        "_holdings": holdings_detail,
                                        "_history": list(reversed(p.get("history", []))),
                                        "_cash": cash / 100,
                                        "_unsettled": unsettled / 100,
                                    }
                                )
                            return rows
                        loop = asyncio.get_event_loop()
                        rows = await loop.run_in_executor(_executor, _work)
                        _admin_state["rows"] = rows
                        admin_table.refresh()

                    @ui.refreshable
                    def admin_table():
                        rows = _admin_state["rows"]
                        if rows is None:
                            ui.label("Loading class data...").classes(
                                "text-muted text-sm"
                            )
                            return
                        if not rows:
                            ui.label("No student accounts.").classes("text-muted")
                            return
                        df = (
                            pd.DataFrame(rows)
                            .sort_values("Net Worth", ascending=False)
                            .reset_index(drop=True)
                        )
                        df["Rank"] = df.index + 1
                        for c in ["Net Worth", "P&L", "Cash", "Stock Value"]:
                            df[c] = df[c].map("${:,.2f}".format)
                        df["Return"] = df["Return"].map("{:+.2f}%".format)

                        columns = [
                            {"name": "Rank", "label": "Rank", "field": "Rank", "align": "center"},
                            {"name": "Student", "label": "Student", "field": "Student"},
                            {"name": "Email", "label": "Email", "field": "Email"},
                            {"name": "Net Worth", "label": "Net Worth", "field": "Net Worth", "align": "right"},
                            {"name": "P&L", "label": "P&L", "field": "P&L", "align": "right"},
                            {"name": "Return", "label": "Return", "field": "Return", "align": "right"},
                            {"name": "Cash", "label": "Cash", "field": "Cash", "align": "right"},
                            {"name": "Stock Value", "label": "Stock Value", "field": "Stock Value", "align": "right"},
                            {"name": "Trades", "label": "Trades", "field": "Trades", "align": "center"},
                        ]
                        table_data = df.to_dict("records")

                        tbl = ui.table(
                            columns=columns,
                            rows=table_data,
                            row_key="Rank",
                            selection="multiple",
                        ).classes("w-full").props("hide-bottom")

                        holdings_dialog = ui.dialog()
                        with holdings_dialog:
                            with ui.card().classes("w-[500px]"):
                                holdings_title = ui.label("").classes("font-bold text-lg")
                                holdings_content = ui.column().classes("w-full mt-2")
                                ui.button("Close", on_click=holdings_dialog.close).props("flat")

                        def _show_holdings(row):
                            name = row.get("Student", "Unknown")
                            email = row.get("Email", "unknown")
                            cash = row.get("_cash", 0)
                            unsettled = row.get("_unsettled", 0)
                            holdings = row.get("_holdings", [])
                            holdings_title.set_text(f"{name} — Holdings")
                            holdings_content.clear()
                            with holdings_content:
                                ui.label(f"Email: {email}").classes("text-sm text-muted")
                                ui.label(f"Cash: ${cash:,.2f}").classes("text-sm text-muted")
                                if unsettled > 0:
                                    ui.label(f"Unsettled: ${unsettled:,.2f}").classes("text-sm text-warning mb-2")
                                else:
                                    ui.element("div").classes("mb-2")
                                ui.separator().classes("my-2")
                                if not holdings:
                                    ui.label("No holdings yet.").classes("text-muted text-sm")
                                else:
                                    for h in sorted(holdings, key=lambda x: x["value"], reverse=True):
                                        ticker = h["ticker"]
                                        shares = h["stock_shares"] = h["shares"]
                                        price = h["price"]
                                        value = h["value"]
                                        cb = h["cost_basis"]
                                        pnl = value - cb if cb > 0 else 0
                                        pnl_cls = "text-positive" if pnl >= 0 else "text-negative"
                                        price_str = f"${price:.2f}" if price else "N/A"
                                        with ui.row().classes("w-full items-center justify-between py-1"):
                                            ui.label(f"{ticker}").classes("font-semibold w-20")
                                            ui.label(f"{shares:.4f} shares").classes("text-sm w-24 text-muted")
                                            ui.label(price_str).classes("text-sm w-20 text-muted")
                                            ui.label(f"${value:,.2f}").classes("text-sm w-24 text-right")
                                            ui.label(f"{'+'if pnl>=0 else ''}{pnl:,.2f}").classes(f"text-sm w-20 text-right {pnl_cls}")
                                history = row.get("_history", [])
                                if history:
                                    ui.separator().classes("my-2")
                                    ui.label("Trade History").classes("font-semibold text-sm mt-1 mb-1")
                                    for h in history:
                                        htype = h.get("type", "")
                                        hticker = h.get("ticker", "")
                                        hshares = h.get("shares", 0)
                                        hprice = h.get("price", 0)
                                        htotal = h.get("total", 0)
                                        hcb = h.get("cost_basis", "")
                                        htax = h.get("tax", "")
                                        htime = h.get("time", "")
                                        badge_cls = "text-positive" if htype == "Buy" else "text-negative"
                                        line1 = f"{htype} {hshares:.4f} {hticker} @ ${hprice:.2f} = ${htotal:.2f}"
                                        parts = [line1]
                                        if hcb != "":
                                            parts.append(f"Cost basis: ${hcb:.2f}")
                                        if htax != "" and float(htax) > 0:
                                            parts.append(f"Tax: ${htax:.2f}")
                                        parts.append(htime)
                                        ui.label("  \u00b7  ".join(parts)).classes(f"text-xs {badge_cls}")
                            holdings_dialog.open()

                        tbl.on("rowClick", lambda e: _show_holdings(e.args[1] if len(e.args) > 1 else {}))

                        ui.label(f"Active: {len(df)}").classes(
                            "text-sm text-muted mt-2"
                        )
                        ui.separator().classes("my-3")

                        confirm_dialog = ui.dialog()

                        with confirm_dialog:
                            with ui.card().classes("w-96"):
                                ui.label("Confirm Removal").classes("font-bold text-lg")
                                confirm_list = ui.label("").classes("text-sm mt-2")
                                ui.separator().classes("my-2")
                                with ui.row().classes("w-full justify-end gap-2"):
                                    ui.button("Cancel", on_click=confirm_dialog.close).props("flat")
                                    ui.button("Remove", on_click=lambda: _execute_remove()).props("color=negative")

                        def _confirm_remove():
                            sel = tbl.selected
                            if not sel:
                                ui.notify("Select students to remove first.", type="warning")
                                return
                            if not is_teacher(email):
                                _audit("UNAUTHORIZED_ADMIN_ATTEMPT", email)
                                ui.notify("Unauthorized.", type="negative")
                                return
                            lines = []
                            for r in sel:
                                name = r.get("Student", "Unknown")
                                em = r.get("Email", "unknown")
                                lines.append(f"  \u2022 {name} ({em})")
                            confirm_list.set_text(f"Remove {len(sel)} student(s)?\n" + "\n".join(lines))
                            confirm_dialog.open()

                        def _execute_remove():
                            if not is_teacher(email):
                                _audit("UNAUTHORIZED_ADMIN_ATTEMPT", email)
                                ui.notify("Unauthorized.", type="negative")
                                confirm_dialog.close()
                                return
                            sel = tbl.selected
                            removed = 0
                            errors = []
                            for r in list(sel):
                                target_email = r.get("Email", "unknown")
                                gcs_key = r.get("_key", "")
                                target_name = r.get("Student", "Unknown")
                                if target_email == email:
                                    errors.append(f"{target_name}: cannot remove yourself")
                                    continue
                                try:
                                    if target_email and target_email != "unknown":
                                        delete_student_profile(target_email)
                                    elif gcs_key:
                                        delete_student_profile_by_key(gcs_key)
                                    else:
                                        errors.append(f"{target_name}: no email or key")
                                        continue
                                    _audit("ADMIN_REMOVE_STUDENT", email, {"target": target_email, "name": target_name})
                                    removed += 1
                                except Exception as e:
                                    errors.append(f"{target_name}: {e}")
                            confirm_dialog.close()
                            if removed:
                                ui.notify(f"Removed {removed} student(s).", type="positive")
                            if errors:
                                ui.notify("Errors:\n" + "\n".join(errors), type="warning")
                            _load_admin()

                        ui.button("Remove Selected", on_click=_confirm_remove).props(
                            "color=negative dense"
                        )

                    admin_table()

                with ui.tab_panel(a2):
                    ui.label("\U0001f9ea Your Sandbox Status").classes("font-semibold")
                    ui.label(
                        "Personal trading in main tabs, filtered from standings."
                    ).classes("text-sm text-muted")
                    ui.json_editor(
                        properties={
                            "Name": profile.get("name"),
                            "Cash": _fmt(profile.get("cash", 0)),
                            "Holdings": {
                                t: p["shares"]
                                for t, p in profile.get("holdings", {}).items()
                            },
                            "Trades": len(profile.get("history", [])),
                        }
                    )

    # ── Lazy loaders ──────────────────────────────────────
    ui.timer(0.1, _load_portfolio, once=True)
    if is_teacher(email):
        ui.timer(0.1, _load_standings, once=True)
    if is_teacher(email):
        ui.timer(0.1, _load_admin, once=True)

    # ── Periodic refresh ──
    async def _tick():
        try:
            loop = asyncio.get_event_loop()
            d = await loop.run_in_executor(_executor, _portfolio, profile)
            _summary_state["data"] = d
            summary.refresh()
            _portfolio_state["data"] = d
            portfolio_content.refresh()
            try:
                positions_info.refresh()
            except Exception:
                pass
            try:
                standings_content.refresh()
            except Exception:
                logger.debug("standings_content.refresh() failed")
            if is_teacher(email):
                try:
                    admin_table.refresh()
                except Exception:
                    logger.debug("admin_table.refresh() failed")
        except Exception:
            logger.debug("_tick refresh failed")
        finally:
            _touch_session()

    ui.timer(300, _tick, active=True)

    async def _heartbeat():
        _touch_session()

    ui.timer(60, _heartbeat, active=True)

    async def _check_session_timeout():
        last = _get_session("last_activity", 0)
        if _get_session("authenticated") and (datetime.utcnow().timestamp() - last > 1800):
            _clear_session()
            app.storage.user.clear()
            ui.navigate.to("/")

    ui.timer(60, _check_session_timeout, active=True)

    async def _check_idle_timeout():
        if not _get_session("authenticated"):
            return
        last_client = _get_session("last_client_activity", 0)
        if (
            datetime.utcnow().timestamp() - last_client > _IDLE_TIMEOUT
            and not is_teacher(email)
        ):
            _clear_session()
            app.storage.user.clear()
            ui.navigate.to("/")

    ui.timer(30, _check_idle_timeout, active=True)

    async def _check_curfew_kick():
        if _in_curfew() and not is_teacher(email) and _get_session("authenticated"):
            _clear_session()
            app.storage.user.clear()
            ui.navigate.to("/")

    ui.timer(60, _check_curfew_kick, active=True)


# ── Security middleware ───────────────────────────────────
# Middleware is defined at the top of the file


# ── Startup ──────────────────────────────────────────────
if __name__ == "__main__":
    ui.run(
        title="Math Finance Simulator",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        storage_secret=_require_env("STORAGE_SECRET"),
        reload=False,
    )
