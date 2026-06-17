import asyncio, json, os, logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import yfinance as yf
import finnhub

from nicegui import app, ui
import pandas as pd
import plotly.graph_objects as go
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi import Request

from utils.auth import get_auth_url, exchange_code, is_teacher
from utils.storage import load_student_profile, save_student_profile, get_gcs_database, delete_student_profile
from utils.market import (
    fetch_stock_market_data, get_dividends,
    CHART_PERIODS, STOCK_TICKERS, ETF_TICKERS, get_top_movers,
    ALL_TICKERS, format_ticker_option, warm_price_cache,
    _flatten_cols,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Cent helpers ──────────────────────────────────────────
def _cents(dollars: float) -> int:
    return int(round(dollars * 100))

def _fmt(cents) -> str:
    cents = int(cents)
    sign = '-' if cents < 0 else ''
    abs_c = abs(cents)
    return f"{sign}${abs_c // 100:,}.{abs_c % 100:02d}"

STARTING_CASH: int = 100000  # $1000.00 in cents

_fh_client = None
def _fh():
    global _fh_client
    if _fh_client is None:
        key = os.environ.get("FINNHUB_API_KEY", "")
        _fh_client = finnhub.Client(api_key=key) if key else None
    return _fh_client

def _relative_time(ts: int) -> str:
    diff = int(datetime.now().timestamp()) - ts
    if diff < 60: return "just now"
    if diff < 3600: return f"{diff // 60}m ago"
    if diff < 86400: return f"{diff // 3600}h ago"
    if diff < 604800: return f"{diff // 86400}d ago"
    return datetime.fromtimestamp(ts).strftime("%b %d")

def _fetch_macro() -> dict:
    result = {}
    try:
        d = _flatten_cols(yf.download('^VIX', period='2y', progress=False, timeout=15))
        v = d['Close'].dropna()
        if not v.empty:
            vv = v.iloc[-1]; result['vix'] = f'{vv:.2f}'
            result['vix_color'] = 'positive' if vv < 15 else 'warning' if vv < 25 else 'negative'
    except: result['vix'] = 'N/A'; result['vix_color'] = ''
    for key, ticker in [('cpi', 'CPIAUCNS'), ('ppi', 'PPIACO'), ('pce', 'PCEPI')]:
        try:
            d = _flatten_cols(yf.download(ticker, period='1y', progress=False, timeout=15))
            s = d['Close'].dropna()
            if len(s) >= 2:
                yoy = ((s.iloc[-1] / s.iloc[0]) - 1) * 100
                result[key] = f'{yoy:+.1f}%'
                result[f'{key}_color'] = 'positive' if yoy < 0 else 'negative'
            else: result[key] = 'N/A'; result[f'{key}_color'] = ''
        except: result[key] = 'N/A'; result[f'{key}_color'] = ''
    try:
        d = _flatten_cols(yf.download('DX-Y.NYB', period='1mo', progress=False, timeout=15))
        s = d['Close'].dropna()
        if not s.empty:
            dv = s.iloc[-1]; chg = ((dv / s.iloc[0]) - 1) * 100
            result['dxy'] = f'{dv:.2f}'; result['dxy_chg'] = f'{chg:+.1f}%'
        else: result['dxy'] = 'N/A'; result['dxy_chg'] = ''
    except: result['dxy'] = 'N/A'; result['dxy_chg'] = ''
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
ui.add_css("""
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
""", shared=True)

# ── Profile cache ────────────────────────────────────────
_profiles: dict = {}

def _migrate_profile(p: dict) -> dict:
    if isinstance(p.get("cash"), int):
        return p
    p["cash"] = int(round(p.get("cash", 0) * 100))
    p["unsettled_cash"] = int(round(p.get("unsettled_cash", 0) * 100))
    p["total_dividends_earned"] = int(round(p.get("total_dividends_earned", 0) * 100))
    p["total_deposits"] = int(round(p.get("total_deposits", 0) * 100))
    for h in p.get("holdings", {}).values():
        h["total_cost"] = int(round(h.get("total_cost", 0) * 100))
    for e in p.get("unsettled_entries", []):
        e["amount"] = int(round(e.get("amount", 0) * 100))
    return p

def _get(email: str):
    if email not in _profiles:
        _profiles[email] = _migrate_profile(load_student_profile(email))
    return _profiles[email]

def _save(email: str, profile: dict):
    _profiles[email] = profile
    save_student_profile(email, profile)

# ── OAuth routes ─────────────────────────────────────────
@app.get('/login')
async def login_route():
    return RedirectResponse(get_auth_url())

def _get_redirect_uri(request):
    env_uri = os.environ.get("REDIRECT_URI", "").strip()
    if env_uri:
        return env_uri
    base = str(request.base_url).strip()
    if 'run.app' in base:
        return base.replace('http://', 'https://').rstrip('/') + '/callback'
    return "http://localhost:8080/callback"

@app.get('/callback')
async def callback_route(code: str, request: Request):
    redirect_uri = _get_redirect_uri(request)
    try:
        user_info = exchange_code(code, redirect_uri=redirect_uri)
        app.storage.user.update({
            'authenticated': True,
            'email': user_info['email'],
            'name': user_info.get('name', 'Student'),
        })
        return RedirectResponse('/')
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        return HTMLResponse(f"""
            <h2 style="color:#ef4444;font-family:sans-serif">Authentication failed</h2>
            <p style="font-family:monospace;color:#6b7280">{str(e)[:300]}</p>
            <a href="/" style="color:#2563eb">Try again</a>
        """)

# ── Legal pages ──────────────────────────────────────────
@ui.page('/privacy')
def privacy_page():
    with ui.column().classes('items-center min-h-screen bg-gray-50'):
        with ui.column().classes('max-w-3xl w-full p-8'):
            ui.link('← Back to App', '/').classes('text-blue-600 mb-4')
            ui.label('Math Finance Simulator').classes('text-2xl font-bold')
            ui.label('Privacy Policy').classes('text-xl font-semibold mt-4')
            ui.label('Last updated: May 29, 2026').classes('text-gray-500 text-sm')
            ui.separator().classes('my-4')
            for title, items in [
                ('Information We Collect', [
                    'Your Google Account information (name, email) for identification.',
                    'Portfolio data (trades, holdings, cash balance) stored in Google Cloud Storage.',
                ]),
                ('How We Use Your Information', [
                    'To provide and maintain the stock market simulation.',
                    'To persist your data across sessions.',
                    'To display classroom standings to your instructor.',
                ]),
                ('Third-Party Services', [
                    'Google Workspace (authentication only)',
                    'Google Cloud Storage (data persistence)',
                    'Yahoo Finance via yfinance (stock price data)',
                ]),
            ]:
                ui.label(title).classes('text-lg font-semibold mt-4')
                for item in items:
                    ui.label(f'\u2022 {item}').classes('text-gray-700 ml-4')
            ui.link('← Back to App', '/').classes('text-blue-600 mt-8')

@ui.page('/terms')
def terms_page():
    with ui.column().classes('items-center min-h-screen bg-gray-50'):
        with ui.column().classes('max-w-3xl w-full p-8'):
            ui.link('← Back to App', '/').classes('text-blue-600 mb-4')
            ui.label('Math Finance Simulator').classes('text-2xl font-bold')
            ui.label('Terms of Service').classes('text-xl font-semibold mt-4')
            ui.label('Last updated: May 29, 2026').classes('text-gray-500 text-sm')
            ui.separator().classes('my-4')
            for title, items in [
                ('Acceptance', ['Educational simulation for classroom use only.']),
                ('Educational Purpose Only', [
                    'Simulation using delayed data from Yahoo Finance.',
                    'All trades are fictional \u2014 no real money is involved.',
                ]),
                ('User Responsibilities', [
                    'Use your school-provided Google Workspace account.',
                    'Do not access other users\' data.',
                ]),
            ]:
                ui.label(title).classes('text-lg font-semibold mt-4')
                for item in items:
                    ui.label(f'\u2022 {item}').classes('text-gray-700 ml-4')
            ui.link('← Back to App', '/').classes('text-blue-600 mt-8')

# ── Data helpers ─────────────────────────────────────────
def _portfolio(profile: dict):
    cash = profile.get("cash", STARTING_CASH) / 100.0
    unsettled = profile.get("unsettled_cash", 0) / 100.0
    holdings = profile.get("holdings", {})
    history = profile.get("history", [])
    total_hold = total_cost = 0.0
    live = []
    for ticker, pos in list(holdings.items()):
        price, _, _ = fetch_stock_market_data(ticker)
        if price is not None and not __import__('math').isnan(price):
            cv = pos['shares'] * price
            total_hold += cv
            tc = pos['total_cost'] / 100.0
            total_cost += tc
            avg = tc / pos['shares']
            ret = ((price - avg) / avg) * 100
            live.append({"Ticker": ticker, "Shares": round(pos['shares'], 4),
                         "Avg Price": f"${avg:.2f}", "Live Price": f"${price:.2f}",
                         "Value": f"${cv:.2f}", "Return": ret})
    total = cash + unsettled + total_hold
    cap = (STARTING_CASH + profile.get("total_deposits", 0)) / 100.0
    pl = total_hold - total_cost
    pl_pct = (pl / total_cost) * 100 if total_cost else 0.0
    return {"cash": cash, "unsettled": unsettled, "holdings": holdings,
            "total_hold": total_hold, "total_cost": total_cost,
            "total": total, "capital": cap, "pl": pl, "pl_pct": pl_pct,
            "live_data": live, "history": history}

def _process_dividends(email: str, profile: dict):
    tracker = profile.setdefault("dividend_tracker", {}); now = datetime.now()
    total_c = 0
    for ticker, pos in list(profile.get("holdings", {}).items()):
        last = tracker.get(ticker)
        divs = get_dividends(ticker)
        if divs is None or divs.empty: continue
        d = divs.index[-1]; amt = float(divs.iloc[-1])
        if last is None:
            tracker[ticker] = d.isoformat(); continue
        if d > datetime.fromisoformat(last):
            a_c = _cents(pos['shares'] * amt)
            if a_c > 0:
                profile["cash"] += a_c
                profile["total_dividends_earned"] = profile.get("total_dividends_earned", 0) + a_c
                profile.setdefault("history", []).append({
                    "type": "dividend", "ticker": ticker, "shares": round(pos['shares'], 4),
                    "dividend_per_share": round(amt, 4), "total": round(pos['shares'] * amt, 2), "time": now.isoformat()})
                total_c += a_c
            tracker[ticker] = d.isoformat()
    if total_c > 0: _save(email, profile)
    return profile

def _process_weekly(email: str, profile: dict):
    now = datetime.now(); last = profile.get("last_weekly_deposit")
    if last:
        w = int((now - datetime.fromisoformat(last)).days / 7)
        if w >= 1:
            a_c = w * 10000  # $100/week in cents
            profile["cash"] += a_c
            profile["total_deposits"] = profile.get("total_deposits", 0) + a_c
            profile["last_weekly_deposit"] = now.isoformat()
            _save(email, profile)
            return a_c, w
    else:
        profile["last_weekly_deposit"] = now.isoformat()
        _save(email, profile)
    return None, 0

def _process_settlement(email: str, profile: dict):
    now = datetime.now(); entries = profile.get("unsettled_entries", [])
    settled_c = 0; remaining = []
    for e in entries:
        if (now - datetime.fromisoformat(e["time"])).total_seconds() >= 86400:
            settled_c += e["amount"]
        else:
            remaining.append(e)
    if settled_c > 0:
        profile["cash"] += settled_c
        profile["unsettled_entries"] = remaining
        profile["unsettled_cash"] = sum(e["amount"] for e in remaining)
        _save(email, profile)
    return profile

def _check_alerts(profile: dict):
    alerts = profile.get("alerts", [])
    triggered = []
    for a in alerts:
        price, _, _ = fetch_stock_market_data(a["ticker"])
        if price is None: continue
        if a["direction"] == "above" and price >= a["price"]:
            triggered.append(f"{a['ticker']} hit ${price:.2f} (above ${a['price']:.2f})")
        elif a["direction"] == "below" and price <= a["price"]:
            triggered.append(f"{a['ticker']} dropped to ${price:.2f} (below ${a['price']:.2f})")
    return triggered

# ── Main page ────────────────────────────────────────────
@ui.page('/')
def main_page():
    if not app.storage.user.get('authenticated'):
        request = ui.context.client.request
        redirect_uri = _get_redirect_uri(request)
        login_url = get_auth_url(redirect_uri=redirect_uri)
        with ui.column().classes('items-center justify-center min-h-screen gap-6'):
            ui.label('\U0001f4c8').classes('text-6xl')
            ui.label('Math Finance Simulator').classes('text-3xl font-bold text-gray-800')
            ui.label('Classroom Stock Market Simulation').classes('text-gray-500 text-lg')
            ui.link('Sign in with Google Workspace', target=login_url
                     ).classes('bg-blue-600 text-white px-8 py-3 rounded-xl shadow-lg hover:shadow-xl text-lg font-semibold no-underline inline-block text-center')
            with ui.row().classes('gap-4 mt-8 text-sm text-gray-400'):
                ui.link('Privacy Policy', '/privacy')
                ui.link('Terms of Service', '/terms')
        return

    # ── Load profile ──
    email = app.storage.user['email']
    name = app.storage.user.get('name', 'Student')
    profile = _get(email)
    if profile is None:
        profile = {"name": name, "cash": STARTING_CASH, "holdings": {}, "alerts": [], "history": [],
                   "unsettled_cash": 0, "unsettled_entries": [], "dividend_tracker": {},
                   "total_dividends_earned": 0}
        _save(email, profile)
    profile["name"] = name
    profile.setdefault("total_dividends_earned", 0)

    # Warm price cache for current user's holdings and alerts
    try:
        tickers_to_warm = set()
        for t in profile.get('holdings', {}).keys(): tickers_to_warm.add(t)
        for a in profile.get('alerts', []): tickers_to_warm.add(a['ticker'])
        if tickers_to_warm: warm_price_cache(list(tickers_to_warm))
    except Exception as e:
        logger.error(f"Error warming price cache: {e}")

    profile = _process_settlement(email, profile)
    deposit_amt, deposit_weeks = _process_weekly(email, profile)
    profile = _process_dividends(email, profile)
    triggered = _check_alerts(profile)

    # ── Top Bar ──
    ui.html(f'''
    <div class="topbar">
        <h1>\U0001f4c8 Math Finance Simulator</h1>
        <div class="user-badge">
            <span class="name">\U0001f464 {name}</span>
            <span class="sep">|</span>
            <span class="email">{email}</span>
        </div>
    </div>
    ''', sanitize=False)

    # ── Summary Bar ──
    _summary_state = {'data': None}
    @ui.refreshable
    def summary():
        p = _summary_state['data']
        if p is None:
            ui.html('<div class="psummary"><div class="metric-box">Loading...</div></div>', sanitize=False)
            return
        sign = '+' if p['pl'] >= 0 else ''
        cls = 'text-positive' if p['pl'] >= 0 else 'text-negative'
        pl_str = f"{sign}${p['pl']:,.2f} ({p['pl_pct']:+.2f}%)"
        items_html = (
            f'<div class="metric-box"><div class="label">Cash Balance</div><div class="value">${p["cash"]:,.2f}</div></div>'
            f'<div class="metric-box"><div class="label">Unsettled Cash</div><div class="value text-warning">${p["unsettled"]:,.2f}</div></div>'
            f'<div class="metric-box"><div class="label">Invested</div><div class="value">${p["total_hold"]:,.2f}</div><div class="sub {cls}">{pl_str}</div></div>'
            f'<div class="metric-box"><div class="label">Dividends</div><div class="value text-positive">{_fmt(profile.get("total_dividends_earned", 0))}</div></div>'
            f'<div class="metric-box"><div class="label">Total Account</div><div class="value">${p["total"]:,.2f}</div></div>'
        )
        ui.html(f'<div class="psummary">{items_html}</div>', sanitize=False)

    async def _load_summary():
        loop = asyncio.get_event_loop()
        _summary_state['data'] = await loop.run_in_executor(None, _portfolio, profile)
        summary.refresh()
    summary()
    ui.timer(0.1, _load_summary, once=True)

    # Banners
    if deposit_amt:
        ui.html(f'<div class="banner banner-positive">\U0001f4b0 Weekly deposit: +{_fmt(deposit_amt)} ({deposit_weeks} week{"s" if deposit_weeks > 1 else ""})</div>')
    for msg in triggered:
        ui.html(f'<div class="banner banner-warning">\U0001f514 {msg}</div>')

    # ── Macro Indicators ──
    _macro_state: dict = {'data': None}
    @ui.refreshable
    def macro_bar():
        d = _macro_state['data']
        if d is None:
            ui.html('<div class="psummary"><div class="metric-box">Loading macro data...</div></div>', sanitize=False)
            return
        items = ''
        for label, val_key, color_key, sub in [
            ('VIX', 'vix', 'vix_color', 'Market fear gauge (<15 calm, >25 panic)'),
            ('CPI', 'cpi', 'cpi_color', 'Consumer inflation, year-over-year'),
            ('PPI', 'ppi', 'ppi_color', 'Producer input costs, year-over-year'),
            ('PCE', 'pce', 'pce_color', "Fed's preferred inflation gauge, YoY"),
            ('DXY', 'dxy', None, f"US Dollar vs majors ({d.get('dxy_chg', '')} 1mo)"),
        ]:
            val = d.get(val_key, 'N/A')
            cls = f'text-{d.get(color_key)}' if color_key else ''
            items += f'<div class="metric-box"><div class="label">{label}</div><div class="value {cls}">{val}</div><div class="sub">{sub}</div></div>'
        ui.html(f'<div class="psummary" style="margin-top:0">{items}</div>', sanitize=False)
    macro_bar()

    async def _macro_worker():
        loop = asyncio.get_event_loop()
        _macro_state['data'] = await loop.run_in_executor(None, _fetch_macro)
        macro_bar.refresh()
    ui.timer(0.1, _macro_worker, once=True)
    ui.timer(300, lambda: _macro_worker(), once=True)

    # ── Tabs ──
    with ui.tabs() as tabs:
        tp = ui.tab('\U0001f4cb Portfolio')
        tt = ui.tab('\U0001fa99 Trade')
        tr = ui.tab('\U0001f52c Research')
        ta = ui.tab('\U0001f514 Alerts')
        if is_teacher(email):
            ts = ui.tab('\U0001f3c6 Standings')

    panels = ui.tab_panels(tabs).classes('page-container')

    # ── PORTFOLIO ──
    with panels:
        with ui.tab_panel(tp):
            _portfolio_state = {'data': None}
            @ui.refreshable
            def portfolio_content():
                p = _portfolio_state['data']
                if p is None:
                    ui.label('Loading portfolio...').classes('text-muted text-sm')
                    return
                holdings = p['holdings']

                labels, values, colors = [], [], []
                if p['cash'] >= 0:
                    labels.append("Cash"); values.append(p['cash']); colors.append("#3b82f6")
                if p['unsettled'] > 0:
                    labels.append("Unsettled"); values.append(p['unsettled']); colors.append("#f59e0b")

                intl = {"VWO","VEA","EFA","IEMG","FXI","EWJ","EWG","EWZ",
                        "INDA","KWEB","EEM","FLTW","TAN","ICLN"}
                us_val = itnl_val = 0.0
                for t, pos in list(holdings.items()):
                    pr, _, _ = fetch_stock_market_data(t)
                    if pr is not None:
                        mv = pos['shares'] * pr
                        if t.upper() in intl: itnl_val += mv
                        else: us_val += mv
                if us_val > 0: labels.append("US"); values.append(us_val); colors.append("#10b981")
                if itnl_val > 0: labels.append("International"); values.append(itnl_val); colors.append("#8b5cf6")

                sl, sv, sc = [], [], []
                palette = ["#3b82f6","#f59e0b","#10b981","#8b5cf6","#f43f5e","#6366f1",
                           "#ec4899","#14b8a6","#f97316","#06b6d4"]
                for i, t in enumerate(holdings):
                    pr, _, _ = fetch_stock_market_data(t)
                    if pr is not None:
                        sv.append(holdings[t]['shares'] * pr)
                        sl.append(t); sc.append(palette[i % len(palette)])

                if labels or sl:
                    with ui.row().classes('w-full gap-4'):
                        if labels:
                            fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.4,
                                marker=dict(colors=colors, line=dict(color='white', width=2)),
                                textinfo='percent', textposition='auto', textfont=dict(size=10))])
                            fig.update_layout(height=280, margin=dict(l=0,r=0,t=20,b=50),
                                              showlegend=True, paper_bgcolor='rgba(0,0,0,0)',
                                              legend=dict(orientation='h', yanchor='bottom', y=-0.3, xanchor='center', x=0.5))
                            with ui.column().classes('chart-container'): ui.plotly(fig).style('width: 100%; height: 280px')
                        if sl:
                            fig = go.Figure(data=[go.Pie(labels=sl, values=sv, hole=0.4,
                                marker=dict(colors=sc, line=dict(color='white', width=2)),
                                textinfo='percent', textposition='auto', textfont=dict(size=10))])
                            fig.update_layout(height=280, margin=dict(l=0,r=0,t=20,b=50),
                                              showlegend=True, paper_bgcolor='rgba(0,0,0,0)',
                                              legend=dict(orientation='h', yanchor='bottom', y=-0.3, xanchor='center', x=0.5))
                            with ui.column().classes('chart-container'): ui.plotly(fig).style('width: 100%; height: 280px')

                with ui.card().classes('w-full mt-4'):
                    ui.label('Positions').classes('font-bold text-lg mb-2')
                    if p['live_data']:
                        df = pd.DataFrame(p['live_data'])
                        df['Return'] = df['Return'].map("{:+.2f}%".format)
                        t = ui.table.from_pandas(df).classes('w-full').props('hide-bottom')
                        t.add_slot('body-cell-Value', '''
                            <td style="text-align:right;vertical-align:middle">
                                {{ props.row.Value }}
                            </td>
                        ''')
                        t.add_slot('body-cell-Return', '''
                            <td style="vertical-align:middle" :class="props.row.Return && props.row.Return.startsWith('-') ? 'text-negative font-semibold text-right' : 'text-positive font-semibold text-right'">
                                {{ props.row.Return }}
                            </td>
                        ''')
                    else:
                        ui.label('No open positions.').classes('text-muted')

                if p['history']:
                    with ui.card().classes('w-full mt-4'):
                        ui.label('Trade History').classes('font-bold text-lg mb-2')
                        ui.table.from_pandas(pd.DataFrame(reversed(p['history']))).classes('w-full').props('hide-bottom')

            async def _load_portfolio():
                loop = asyncio.get_event_loop()
                _portfolio_state['data'] = await loop.run_in_executor(None, _portfolio, profile)
                portfolio_content.refresh()
            portfolio_content()

        # ── TRADE ──
        with ui.tab_panel(tt):
            pending = {'data': None}
            opts = {t: format_ticker_option(t) for t in ALL_TICKERS}
            sel = ui.select(options=opts, label='Search symbol', clearable=True).classes('w-full').props('use-input input-debounce=300')
            price_val = ui.label().classes('text-xl font-bold')
            price_sub = ui.label().classes('text-sm text-muted')
            action = ui.radio(['Buy', 'Sell'], value='Buy').props('inline dense').classes('mt-1')
            mode = ui.radio(['Shares', 'Amount ($)'], value='Shares').props('inline dense')
            shares_in = ui.number(label='Shares', value=1.0, min=0.001, step=0.1, format='%.4f').classes('w-full')
            amount_in = ui.number(label='Amount ($)', value=100.0, min=1.0, step=10.0).classes('w-full')
            amount_in.set_visibility(False)
            preview = ui.label().classes('text-sm text-muted mt-1')

            def _upd_sel():
                t = sel.value
                if t:
                    pr, _, company = fetch_stock_market_data(t)
                    if pr is not None:
                        price_val.set_text(f'${pr:.2f}')
                        price_sub.set_text(company)
                    else:
                        price_val.set_text('Price unavailable')
                        price_sub.set_text('')
                else:
                    price_val.set_text(''); price_sub.set_text('')

            def _upd_mode():
                s = mode.value == 'Shares'
                shares_in.set_visibility(s)
                amount_in.set_visibility(not s)

            def _upd_preview():
                t = sel.value
                if not t: preview.set_text(''); return
                pr, _, _ = fetch_stock_market_data(t)
                if pr is None: preview.set_text(''); return
                cost = (shares_in.value * pr) if mode.value == 'Shares' else amount_in.value
                cost_c = _cents(cost)
                c_pct = (cost_c / profile['cash']) * 100 if profile['cash'] > 0 else 0
                p = _portfolio(profile)
                if action.value == 'Buy':
                    ex = profile['holdings'].get(t, {}).get('shares', 0)
                    w = ((cost + (ex * pr)) / p['total']) * 100 if p['total'] > 0 else 0
                    preview.set_text(f'\u2248 ${cost:,.2f}  \u00b7  {c_pct:.1f}% of cash  \u00b7  est. weight {w:.1f}%')
                else:
                    if t in profile['holdings']:
                        rm = max(profile['holdings'][t]['shares'] - shares_in.value, 0)
                        w = ((rm * pr) / p['total']) * 100 if p['total'] > 0 else 0
                        preview.set_text(f'\u2248 {shares_in.value:.4f} shares  \u00b7  est. new weight {w:.1f}%')

            sel.on_value_change(lambda: _upd_sel()); sel.on_value_change(lambda: _upd_preview())
            action.on_value_change(lambda: _upd_preview()); mode.on_value_change(lambda: _upd_preview())
            mode.on_value_change(lambda: _upd_mode())
            shares_in.on_value_change(lambda: _upd_preview()); amount_in.on_value_change(lambda: _upd_preview())

            @ui.refreshable
            def confirm_card():
                d = pending['data']
                if not d: return
                with ui.card().classes('w-full bg-blue-50 border-2 border-blue-200'):
                    ui.label(f"Confirm {d['action']}: {d['shares']:.4f} shares of {d['ticker']} at ${d['price']:.2f} = ${d['cost']:.2f}").classes('font-semibold text-blue-900')
                    with ui.row().classes('gap-3 mt-3'):
                        ui.button(f"\u2705 Confirm {d['action']}", on_click=lambda: _exec(d)).props('color=primary')
                        ui.button('\u274c Cancel', on_click=lambda: (pending.update({'data': None}), confirm_card.refresh()))

            def _exec(data):
                t = data['ticker']
                cost_c = _cents(data['cost'])
                if data['action'] == 'Buy':
                    profile['cash'] -= cost_c
                    if t in profile['holdings']:
                        profile['holdings'][t]['shares'] += data['shares']
                        profile['holdings'][t]['total_cost'] += cost_c
                    else:
                        profile['holdings'][t] = {'shares': data['shares'], 'total_cost': cost_c}
                    profile.setdefault('history', []).append({
                        'type': 'Buy', 'ticker': t, 'shares': round(data['shares'], 4),
                        'price': round(data['price'], 2), 'total': round(data['cost'], 2),
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M')})
                else:
                    owned = profile['holdings'][t]['shares']
                    frac = data['shares'] / owned
                    cb = int(round(frac * profile['holdings'][t]['total_cost']))
                    profit_c = cost_c - cb
                    tax_c = max(0, int(round(profit_c * 0.15)))
                    net_c = cost_c - tax_c
                    profile['unsettled_cash'] = profile.get('unsettled_cash', 0) + net_c
                    profile.setdefault('unsettled_entries', []).append({
                        'amount': net_c, 'time': datetime.now().isoformat()})
                    profile['holdings'][t]['shares'] -= data['shares']
                    profile['holdings'][t]['total_cost'] -= cb
                    if profile['holdings'][t]['shares'] <= 0: del profile['holdings'][t]
                    profile.setdefault('history', []).append({
                        'type': 'Sell', 'ticker': t, 'shares': round(data['shares'], 4),
                        'price': round(data['price'], 2), 'total': round(data['cost'], 2),
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M')})
                _save(email, profile)
                pending['data'] = None
                confirm_card.refresh()
                summary.refresh(); portfolio_content.refresh()
                try: movers.refresh()
                except: pass
                try: standings_content.refresh()
                except: pass
                ui.notify('\u2705 Trade executed!', type='positive')

            def _review():
                t = sel.value
                if not t: ui.notify('Select a ticker', type='warning'); return
                pr, _, _ = fetch_stock_market_data(t)
                if pr is None: ui.notify(f'Price unavailable for {t}', type='negative'); return
                cost = (shares_in.value * pr) if mode.value == 'Shares' else amount_in.value
                cost_c = _cents(cost)
                sh = (shares_in.value if mode.value == 'Shares' else cost / pr)
                a = action.value
                err = None
                if a == 'Buy' and cost_c > profile['cash']:
                    err = f'Insufficient cash ({_fmt(profile["cash"])} available, {_fmt(cost_c)} needed)'
                elif a == 'Sell':
                    if t not in profile['holdings']: err = 'Not owned.'
                    else:
                        o = profile['holdings'][t]['shares']
                        if mode.value == 'Shares' and sh > o + 0.0001: err = f'Only {o:.4f} shares owned.'
                        elif mode.value == 'Amount ($)' and cost > o * pr + 0.01: err = 'Exceeds position value.'
                if err: ui.notify(err, type='negative'); return
                pending['data'] = {'action': a, 'ticker': t, 'shares': sh, 'cost': cost, 'price': pr}
                confirm_card.refresh()

            with ui.row().classes('w-full gap-4'):
                with ui.card().classes('trade-ticket'):
                    ui.label('Trade Ticket').classes('font-bold text-lg mb-3')
                    sel
                    with ui.row().classes('items-baseline gap-2 mt-1'):
                        price_val; price_sub
                    action; mode; shares_in; amount_in
                    preview
                    ui.button('\U0001f4cb Review Order', on_click=_review).props('color=primary').classes('w-full mt-2')
                    confirm_card()

                with ui.card().classes('market-movers'):
                    ui.label('\U0001f4ca Market Movers').classes('font-bold text-lg mb-3')
                    _movers_state: dict = {'data': [], 'loaded': False}
                    async def _load_movers():
                        def _fetch():
                            all_data = []
                            stock_groups = [STOCK_TICKERS[i:i+100] for i in range(0, len(STOCK_TICKERS), 100)]
                            for group in stock_groups + [ETF_TICKERS]:
                                try:
                                    all_data.extend(list(get_top_movers(tuple(group))))
                                except Exception as e:
                                    logger.error(f"Movers batch error ({len(group)} tickers): {e}")
                            return all_data
                        loop = asyncio.get_event_loop()
                        _movers_state['data'] = await loop.run_in_executor(None, _fetch)
                        _movers_state['loaded'] = True
                        movers.refresh()
                    @ui.refreshable
                    def                     movers():
                        if not _movers_state['loaded']:
                            ui.label('Loading market data...').classes('text-muted text-sm')
                        else:
                            for label, items in [("Stocks", [x for x in _movers_state['data'] if x[0] in STOCK_TICKERS]),
                                                 ("ETFs", [x for x in _movers_state['data'] if x[0] in ETF_TICKERS])]:
                                gainers = [x for x in items if x[3] > 0][:5]
                                losers = [x for x in items if x[3] < 0][-5:][::-1]
                                if not gainers and not losers:
                                    ui.label(f'{label}: No data').classes('text-muted text-xs'); continue
                                with ui.column().classes('w-full gap-1 mb-3'):
                                    if gainers:
                                        ui.label(f'{label} \u2191').classes('text-xs font-semibold text-positive')
                                        for tick, n, p, c in gainers:
                                            with ui.row().classes('w-full items-center justify-between bg-green-50 rounded-lg px-3 py-1.5'):
                                                ui.label(tick).classes('text-xs font-bold w-14')
                                                ui.label(n[:18]).classes('text-xs text-muted flex-1 truncate')
                                                ui.label(f'${p:.2f}').classes('text-xs w-16 text-right')
                                                ui.label(f'{c:+.2f}%').classes(f'text-xs font-semibold w-16 text-right text-positive')
                                    if losers:
                                        ui.label(f'{label} \u2193').classes('text-xs font-semibold text-negative mt-1')
                                        for tick, n, p, c in losers:
                                            with ui.row().classes('w-full items-center justify-between bg-red-50 rounded-lg px-3 py-1.5'):
                                                ui.label(tick).classes('text-xs font-bold w-14')
                                                ui.label(n[:18]).classes('text-xs text-muted flex-1 truncate')
                                                ui.label(f'${p:.2f}').classes('text-xs w-16 text-right')
                                                ui.label(f'{c:+.2f}%').classes(f'text-xs font-semibold w-16 text-right text-negative')
                                ui.separator().classes('my-1')
                    movers()

        # ── RESEARCH ──
        with ui.tab_panel(tr):
            with ui.row().classes('w-full gap-4'):
                with ui.card().classes('research-vol'):
                    ui.label('Volatility Calculator').classes('font-bold text-lg mb-3')
                    vs = ui.select(options=opts, label='Search symbol', clearable=True).classes('w-full').props('use-input input-debounce=300')
                    vp = ui.select(options=CHART_PERIODS, value='3mo', label='Period').classes('w-full')
                    v_std = ui.label('\u2014').classes('text-2xl font-bold')
                    v_range = ui.label('\u2014').classes('text-2xl font-bold')
                    v_desc = ui.label('Pick a stock to calculate volatility.').classes('text-sm text-muted mt-2')

                    async def _vol_worker(t, period):
                        try:
                            loop = asyncio.get_event_loop()
                            d = await loop.run_in_executor(
                                None, lambda: _flatten_cols(yf.download(t, period=period, progress=False, timeout=20)))
                            logger.info(f"Volatility: downloaded {len(d) if d is not None else 0} rows for {t}")
                            if d is None or len(d) < 2:
                                v_std.set_text('N/A'); v_range.set_text('N/A'); v_desc.set_text('Not enough data.'); return
                            d['chg'] = d['Close'].pct_change() * 100
                            std = d[['Close', 'chg']].dropna()['chg'].std()
                            pl = CHART_PERIODS.get(period, period).lower()
                            risk = 'very low' if std < 0.5 else 'low' if std < 1.0 else 'moderate' if std < 1.5 else 'high' if std < 2.5 else 'very high'
                            v_std.set_text(f'{std:.2f}%'); v_range.set_text(f'\u00b1{std:.2f}%')
                            v_desc.set_text(f'Over {pl}, {t} typically moves \u00b1{std:.1f}% per day. Risk: {risk}.')
                            logger.info(f"Volatility: std={std:.2f}%, risk={risk} for {t}")
                        except Exception as e:
                            logger.error(f"Volatility calc error for {t}: {e}", exc_info=True)
                            v_std.set_text('N/A'); v_range.set_text('N/A'); v_desc.set_text('Error fetching data.')

                    def _vol():
                        t = vs.value
                        if not t: v_std.set_text('\u2014'); v_range.set_text('\u2014'); v_desc.set_text('Pick a stock.'); return
                        p = vp.value; ui.timer(0, lambda t=t, p=p: _vol_worker(t, p), once=True)

                    vs.on_value_change(lambda: _vol()); vp.on_value_change(lambda: _vol())

                    with ui.row().classes('w-full gap-2 mt-2'):
                        with ui.column().classes('flex-1 bg-gray-50 rounded-lg p-3'):
                            ui.label('Daily Volatility').classes('text-xs text-muted uppercase tracking-wider font-medium')
                            v_std
                        with ui.column().classes('flex-1 bg-gray-50 rounded-lg p-3'):
                            ui.label('Typical Range').classes('text-xs text-muted uppercase tracking-wider font-medium')
                            v_range
                    v_desc

                with ui.card().classes('research-chart'):
                    ui.label('Price History').classes('font-bold text-lg mb-3')
                    with ui.row().classes('gap-2'):
                        cp_sel = ui.select(options=CHART_PERIODS, value='3mo', label='Period').classes('w-40')
                        cs_sel = ui.select(options={'Line': 'Line', 'Candlestick': 'Candlestick'}, value='Line', label='Style').classes('w-36')
                    chart_price = ui.label().classes('text-3xl font-bold')
                    chart_sub = ui.label().classes('text-sm text-muted')
                    ui.html('<div id="tvchart" style="width:100%;height:380px;position:relative;overflow:hidden;box-sizing:border-box"></div>', sanitize=False)

                    ui.run_javascript('''
var _tvt = Date.now();
(function initTv() {
    try {
        if (typeof LightweightCharts === 'undefined') { if (Date.now() - _tvt < 10000) setTimeout(initTv, 100); return; }
        var el = document.getElementById('tvchart');
        if (!el) { if (Date.now() - _tvt < 10000) setTimeout(initTv, 100); return; }
        if (window.__tv && window.__tv.ready) return;
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
                var w = el.clientWidth, h = el.clientHeight;
                if (w > 0 && h > 0) { c.resize(w, h); console.log('TV RO resized', w, 'x', h); }
            }).observe(el);
        }
        console.log('TV chart initialized', iw, 'x', ih);
    } catch(e) { console.error('TV init error:', e); if (Date.now() - _tvt < 10000) setTimeout(initTv, 100); }
})();''')

                    async def _chart_worker(t, period, style):
                        try:
                            loop = asyncio.get_event_loop()
                            pr, _, company = await loop.run_in_executor(None, fetch_stock_market_data, t)
                            chart_price.set_text(f'${pr:.2f}' if pr else '')
                            chart_sub.set_text(company if pr else '')
                            hist = await loop.run_in_executor(
                                None, lambda: _flatten_cols(yf.download(t, period=period, progress=False, timeout=20)))
                            if hist is None or len(hist) < 2:
                                logger.error(f"Chart: not enough history for {t} (period={period}, rows={len(hist) if hist is not None else 'None'})")
                                ui.run_javascript('if (window.__tv) { window.__tv.candle.setData([]); window.__tv.line.setData([]); }')
                                return
                            logger.info(f"Chart: loaded {len(hist)} rows for {t} ({period})")
                            data = []
                            for idx, row in hist.iterrows():
                                data.append({
                                    'time': int(idx.timestamp()),
                                    'open': float(row['Open']), 'high': float(row['High']),
                                    'low': float(row['Low']), 'close': float(row['Close']),
                                 })
                            line_data = [{'time': d['time'], 'value': d['close']} for d in data]
                            candle_vis = 'true' if style == 'Candlestick' else 'false'
                            line_vis = 'true' if style == 'Line' else 'false'
                            ui.run_javascript(f'''
if (!window.__tv) return;
var tvEl = document.getElementById('tvchart');
if (tvEl && tvEl.clientWidth > 0) {{ window.__tv.chart.resize(tvEl.clientWidth, tvEl.clientHeight); }}
window.__tv.candle.setData({json.dumps(data)});
window.__tv.line.setData({json.dumps(line_data)});
window.__tv.candle.applyOptions({{visible: {candle_vis}}});
window.__tv.line.applyOptions({{visible: {line_vis}}});
window.__tv.chart.timeScale().fitContent();
                            ''')
                            logger.info(f"Chart: rendered {len(data)} candles for {t} ({style})")
                        except Exception as e:
                            logger.error(f"Chart error for {t}: {e}", exc_info=True)

                    def _chart():
                        t = vs.value
                        if not t: chart_price.set_text(''); chart_sub.set_text(''); return
                        p = cp_sel.value; s = cs_sel.value
                        ui.timer(0, lambda t=t, p=p, s=s: _chart_worker(t, p, s), once=True)

                    cp_sel.on_value_change(lambda: _chart()); cs_sel.on_value_change(lambda: _chart())
                    vs.on_value_change(lambda: _chart())

            # ══ Research: News ══
            ui.separator().classes('mt-4')
            with ui.card().classes('w-full'):
                ui.label('\U0001f4f0 Market News').classes('font-bold text-lg mb-3')
                _news_container = ui.label()
                _news_state = {'ticker': None}

                async def _news_worker(t):
                    try:
                        loop = asyncio.get_event_loop()
                        today = datetime.now().strftime('%Y-%m-%d')
                        week_ago = (datetime.now().timestamp() - 7 * 86400)
                        from_date = datetime.fromtimestamp(week_ago).strftime('%Y-%m-%d')
                        articles = await loop.run_in_executor(
                            None, lambda: _fh().company_news(t, _from=from_date, to=today))
                        articles = [a for a in articles if 'yahoo' not in a.get('source', '').lower()][:5]
                        _news_state['articles'] = articles
                        _news_state['ticker'] = t
                        _news_container.set_text('')
                        _news_container.clear()
                        if not articles:
                            with _news_container:
                                ui.label('No recent news.').classes('text-muted text-sm')
                            return
                        with _news_container:
                            for a in articles[:5]:
                                ts = a.get('datetime', 0)
                                headline = a.get('headline', '')
                                url = a.get('url', '')
                                source = a.get('source', '')
                                summary = a.get('summary', '')
                                with ui.card().classes('w-full q-pa-sm q-mb-sm'):
                                    with ui.row().classes('items-start gap-2'):
                                        ui.link(headline, url, new_tab=True).classes('font-semibold text-sm')
                                        ui.label(f'— {source} \u00b7 {_relative_time(ts)}').classes('text-xs text-muted')
                                    if summary:
                                        ui.label(summary).classes('text-xs text-gray-600 line-clamp-2')
                    except Exception as e:
                        logger.error(f"News error for {t}: {e}", exc_info=True)
                        _news_container.set_text(f'Error loading news: {e}')

                def _load_news():
                    t = vs.value
                    if not t:
                        _news_container.set_text('Select a stock to view news.')
                        return
                    _news_container.set_text('Loading news...')
                    ui.timer(0, lambda t=t: _news_worker(t), once=True)

                vs.on_value_change(lambda: _load_news())

        # ── ALERTS ──
        with ui.tab_panel(ta):
            with ui.card().classes('w-full'):
                ui.label('Price Alerts').classes('font-bold text-lg mb-2')
                ui.label('Notify when a stock crosses a target price.').classes('text-sm text-muted mb-3')
                asel = ui.select(options=opts, label='Search symbol', clearable=True).classes('w-56').props('use-input input-debounce=300')
                adir = ui.select(options={'above': 'Above', 'below': 'Below'}, value='above').classes('w-32')
                apr = ui.number(label='Target Price', value=200.0, min=0.01, step=1.0).classes('w-32')

                @ui.refreshable
                def alert_list():
                    for i, a in enumerate(profile.get('alerts', [])):
                        with ui.row().classes('items-center gap-3 py-2 border-b border-gray-100'):
                            ui.label(a['ticker']).classes('font-semibold w-20')
                            ui.label(f"\u2192 {a['direction']}").classes('text-muted w-20 text-sm')
                            ui.label(f"${a['price']:.2f}").classes('w-20 text-sm')
                            ui.button('\u2715', on_click=lambda idx=i: _del(idx)).props('flat dense color=negative')

                def _add():
                    t = asel.value
                    if not t: ui.notify('Select a ticker', type='warning'); return
                    profile.setdefault('alerts', []).append({'ticker': t, 'direction': adir.value, 'price': apr.value})
                    _save(email, profile); alert_list.refresh(); ui.notify('Alert added!', type='positive')

                def _del(idx):
                    profile.get('alerts', []).pop(idx); _save(email, profile); alert_list.refresh()

                with ui.row().classes('items-center gap-2'):
                    asel; adir; apr
                    ui.button('+ Add', on_click=_add).props('color=primary')
                alert_list()

        # ── STANDINGS ──
        _standings_state: dict = {'rows': None}
        if is_teacher(email):
            with ui.tab_panel(ts):
                with ui.card().classes('w-full'):
                    ui.label('\U0001f3c6 Classroom Standings').classes('font-bold text-lg mb-3')
                    def _load_standings():
                        db = get_gcs_database()
                        if not db: _standings_state['rows'] = []; standings_content.refresh(); return
                        rows = []
                        for e, p in db.items():
                            if e == 'rpiana@stjohnsguam.com': continue
                            p = _migrate_profile(p)
                            mv = 0.0
                            for t, pos in p.get('holdings', {}).items():
                                pr, _, _ = fetch_stock_market_data(t)
                                if pr is not None: mv += pos['shares'] * pr
                            cash = p.get('cash', STARTING_CASH)
                            nw = (cash / 100) + mv
                            rows.append({'Student': p.get('name', 'Student'), 'Net Worth': nw, 'Return': ((nw-(STARTING_CASH/100))/(STARTING_CASH/100))*100})
                        _standings_state['rows'] = rows
                        standings_content.refresh()
                    @ui.refreshable
                    def standings_content():
                        rows = _standings_state['rows']
                        if rows is None:
                            ui.label('Loading standings...').classes('text-muted text-sm')
                            return
                        if not rows:
                            ui.label('No participants.').classes('text-muted')
                            return
                        df = pd.DataFrame(rows).sort_values('Net Worth', ascending=False).reset_index(drop=True)
                        df['Rank'] = df.index + 1
                        df['Net Worth'] = df['Net Worth'].map('${:,.2f}'.format)
                        df['Return'] = df['Return'].map('{:+.2f}%'.format)
                        ui.table.from_pandas(df[['Rank', 'Student', 'Net Worth', 'Return']]).classes('w-full').props('hide-bottom')
                    standings_content()

    # ── Teacher admin ─────────────────────────────────────
    if is_teacher(email):
        with ui.card().classes('w-full page-container p-4 mt-4 border-t-2 border-blue-200'):
            ui.label('\U0001f468\u200d\U0001f3eb Teacher Administration').classes('font-bold text-lg mb-2')
            with ui.tabs().classes('w-full') as at:
                a1 = ui.tab('\U0001f4ca Class Portfolio Data')
                a2 = ui.tab('\U0001f9ea Sandbox')

            with ui.tab_panels(at):
                with ui.tab_panel(a1):
                    _admin_state: dict = {'rows': None}
                    def _load_admin():
                        db = get_gcs_database()
                        if not db: _admin_state['rows'] = []; admin_table.refresh(); return
                        rows = []
                        for e, p in db.items():
                            if e == 'rpiana@stjohnsguam.com': continue
                            p = _migrate_profile(p)
                            mv = 0.0
                            for t, pos in p.get('holdings', {}).items():
                                pr, _, _ = fetch_stock_market_data(t)
                                if pr is not None: mv += pos['shares'] * pr
                            cash = p.get('cash', STARTING_CASH)
                            nw = (cash / 100) + mv
                            pl = nw - (STARTING_CASH / 100)
                            rows.append({'Student': p.get('name', 'Unknown'), 'Email': e.split('@')[0],
                                         'Net Worth': nw, 'P&L': pl, 'Return': (pl / (STARTING_CASH / 100)) * 100,
                                         'Cash': cash / 100, 'Stock Value': mv,
                                         'Trades': len(p.get('history', []))})
                        _admin_state['rows'] = rows
                        admin_table.refresh()
                    @ui.refreshable
                    def admin_table():
                        rows = _admin_state['rows']
                        if rows is None:
                            ui.label('Loading class data...').classes('text-muted text-sm')
                            return
                        if not rows:
                            ui.label('No student accounts.').classes('text-muted')
                            return
                        df = pd.DataFrame(rows).sort_values('Net Worth', ascending=False).reset_index(drop=True)
                        df['Rank'] = df.index + 1
                        for c in ['Net Worth', 'P&L', 'Cash', 'Stock Value']:
                            df[c] = df[c].map('${:,.2f}'.format)
                        df['Return'] = df['Return'].map('{:+.2f}%'.format)
                        ui.table.from_pandas(df).classes('w-full').props('hide-bottom')
                        ui.label(f'Active: {len(df)}').classes('text-sm text-muted mt-2')
                        ui.separator().classes('my-3')
                        ui.label('\u2757 Remove Student').classes('font-semibold text-sm')
                        with ui.row().classes('items-center gap-2'):
                            rem_email = ui.input('Full email address').props('outlined dense').classes('w-64')
                            rem_status = ui.label('').classes('text-sm')
                            def _do_remove():
                                email = rem_email.value.strip()
                                if not email:
                                    rem_status.set_text('Enter an email.'); rem_status.classes('text-warning')
                                    return
                                try:
                                    delete_student_profile(email)
                                    rem_status.set_text(f'Removed {email}.'); rem_status.classes('text-positive')
                                    rem_email.value = ''
                                    _load_admin()
                                except Exception as e:
                                    rem_status.set_text(f'Error: {e}'); rem_status.classes('text-negative')
                            ui.button('Remove', on_click=_do_remove).props('color=negative dense')
                    admin_table()

                with ui.tab_panel(a2):
                    ui.label('\U0001f9ea Your Sandbox Status').classes('font-semibold')
                    ui.label('Personal trading in main tabs, filtered from standings.').classes('text-sm text-muted')
                    ui.json_editor(properties={
                        'Name': profile.get('name'),
                        'Cash': _fmt(profile.get('cash', 0)),
                        'Holdings': {t: p['shares'] for t, p in profile.get('holdings', {}).items()},
                        'Trades': len(profile.get('history', []))
                    })

    # ── Lazy loaders ──────────────────────────────────────
    ui.timer(0.1, _load_portfolio, once=True)
    ui.timer(0.1, _load_movers, once=True)
    if is_teacher(email):
        ui.timer(0.1, _load_standings, once=True)
    if is_teacher(email):
        ui.timer(0.1, _load_admin, once=True)

    # ── Periodic refresh ──
    async def _tick():
        loop = asyncio.get_event_loop()
        d = await loop.run_in_executor(None, _portfolio, profile)
        _summary_state['data'] = d
        summary.refresh()
        _portfolio_state['data'] = d
        portfolio_content.refresh()
        try: standings_content.refresh()
        except: pass
        if is_teacher(email):
            try: admin_table.refresh()
            except: pass
    ui.timer(300, _tick, active=True)

# ── Startup ──────────────────────────────────────────────
ui.run(
    title='Math Finance Simulator',
    host='0.0.0.0',
    port=int(os.environ.get('PORT', 8080)),
    storage_secret=os.environ.get('STORAGE_SECRET', 'dev-secret-change-me'),
    reload=False,
)
