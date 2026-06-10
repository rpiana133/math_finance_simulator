import json, os, logging
from datetime import datetime

from nicegui import app, ui
import pandas as pd
import plotly.graph_objects as go
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi import Request

from utils.auth import get_auth_url, exchange_code, is_teacher
from utils.storage import load_student_profile, save_student_profile, get_gcs_database
from utils.market import (
    fetch_stock_market_data, fetch_full_history, get_dividends,
    CHART_PERIODS, STOCK_TICKERS, ETF_TICKERS, get_top_movers,
    ALL_TICKERS, format_ticker_option, warm_price_cache,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Shared head HTML (loaded before any page) ─────────────
ui.add_head_html(
    '<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">'
    '<link href="https://cdnjs.cloudflare.com/ajax/libs/material-design-icons/3.0.2/iconfont/material-icons.css" rel="stylesheet">',
    shared=True,
)

# ── Profile cache ────────────────────────────────────────
_profiles: dict = {}

def _get(email: str):
    if email not in _profiles:
        _profiles[email] = load_student_profile(email)
    return _profiles[email]

def _save(email: str, profile: dict):
    _profiles[email] = profile
    save_student_profile(email, profile)

# ── OAuth routes ─────────────────────────────────────────
@app.get('/login')
async def login_route():
    return RedirectResponse(get_auth_url())

# ── Legal pages ──────────────────────────────────────────
@ui.page('/privacy')
def privacy_page():
    ui.query('body').classes('bg-gray-50')
    with ui.column().classes('max-w-3xl mx-auto p-8'):
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
                ui.label(f'• {item}').classes('text-gray-700 ml-4')
        ui.link('← Back to App', '/').classes('text-blue-600 mt-8')

@ui.page('/terms')
def terms_page():
    ui.query('body').classes('bg-gray-50')
    with ui.column().classes('max-w-3xl mx-auto p-8'):
        ui.link('← Back to App', '/').classes('text-blue-600 mb-4')
        ui.label('Math Finance Simulator').classes('text-2xl font-bold')
        ui.label('Terms of Service').classes('text-xl font-semibold mt-4')
        ui.label('Last updated: May 29, 2026').classes('text-gray-500 text-sm')
        ui.separator().classes('my-4')
        for title, items in [
            ('Acceptance', ['Educational simulation for classroom use only.']),
            ('Educational Purpose Only', [
                'Simulation using delayed data from Yahoo Finance.',
                'All trades are fictional — no real money is involved.',
            ]),
            ('User Responsibilities', [
                'Use your school-provided Google Workspace account.',
                'Do not access other users\' data.',
            ]),
        ]:
            ui.label(title).classes('text-lg font-semibold mt-4')
            for item in items:
                ui.label(f'• {item}').classes('text-gray-700 ml-4')
        ui.link('← Back to App', '/').classes('text-blue-600 mt-8')

def get_dynamic_redirect_uri(request):
    env_uri = os.environ.get("REDIRECT_URI", "").strip()
    if env_uri:
        logger.info("Using REDIRECT_URI env var: %s", env_uri)
        return env_uri
    base_url = str(request.base_url).strip()
    if 'run.app' in base_url:
        result = base_url.replace('http://', 'https://').rstrip('/') + '/callback'
        logger.info("Auto-detected redirect URI: %s", result)
        return result
    return "http://localhost:8080/callback"

# ── Auth callback ────────────────────────────────────────
@app.get('/callback')
async def callback_route(code: str, request: Request):
    base = str(request.base_url).replace('http://', 'https://').rstrip('/')
    redirect_uri = base + '/callback'
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

# ── Data helpers ─────────────────────────────────────────
def _portfolio(profile: dict):
    cash = profile.get("cash", 1000.0)
    unsettled = profile.get("unsettled_cash", 0.0)
    holdings = profile.get("holdings", {})
    history = profile.get("history", [])
    total_hold = total_cost = 0.0
    live = []
    for ticker, pos in list(holdings.items()):
        price, _, _ = fetch_stock_market_data(ticker)
        if price is not None and not __import__('math').isnan(price):
            cv = pos['shares'] * price
            total_hold += cv
            total_cost += pos['total_cost']
            avg = pos['total_cost'] / pos['shares']
            ret = ((price - avg) / avg) * 100
            live.append({"Ticker": ticker, "Shares": round(pos['shares'], 4),
                         "Avg Price": f"${avg:.2f}", "Live Price": f"${price:.2f}",
                         "Value": f"${cv:.2f}", "Return": ret})
    total = cash + unsettled + total_hold
    cap = 1000.0 + profile.get("total_deposits", 0.0)
    pl = total_hold - total_cost
    pl_pct = (pl / total_cost) * 100 if total_cost else 0.0
    return {"cash": cash, "unsettled": unsettled, "holdings": holdings,
            "total_hold": total_hold, "total_cost": total_cost,
            "total": total, "capital": cap, "pl": pl, "pl_pct": pl_pct,
            "live_data": live, "history": history}

def _process_dividends(email: str, profile: dict):
    tracker = profile.setdefault("dividend_tracker", {}); now = datetime.now()
    total = 0.0
    for ticker, pos in list(profile.get("holdings", {}).items()):
        last = tracker.get(ticker)
        divs = get_dividends(ticker)
        if divs is None or divs.empty: continue
        d = divs.index[-1]; amt = float(divs.iloc[-1])
        if last is None:
            tracker[ticker] = d.isoformat(); continue
        if d > datetime.fromisoformat(last):
            a = pos['shares'] * amt
            if a > 0:
                profile["cash"] = round(profile["cash"] + a, 2)
                profile["total_dividends_earned"] = round(profile.get("total_dividends_earned", 0.0) + a, 2)
                profile.setdefault("history", []).append({
                    "type": "dividend", "ticker": ticker, "shares": round(pos['shares'], 4),
                    "dividend_per_share": round(amt, 4), "total": round(a, 2), "time": now.isoformat()})
                total += a
            tracker[ticker] = d.isoformat()
    if total > 0: _save(email, profile)
    return profile

def _process_weekly(email: str, profile: dict):
    now = datetime.now(); last = profile.get("last_weekly_deposit")
    if last:
        w = int((now - datetime.fromisoformat(last)).days / 7)
        if w >= 1:
            a = w * 100
            profile["cash"] = round(profile["cash"] + a, 2)
            profile["total_deposits"] = round(profile.get("total_deposits", 0.0) + a, 2)
            profile["last_weekly_deposit"] = now.isoformat()
            _save(email, profile)
            return a, w
    else:
        profile["last_weekly_deposit"] = now.isoformat()
        _save(email, profile)
    return None, 0

def _process_settlement(email: str, profile: dict):
    now = datetime.now(); entries = profile.get("unsettled_entries", [])
    settled = 0.0; remaining = []
    for e in entries:
        if (now - datetime.fromisoformat(e["time"])).total_seconds() >= 86400:
            settled += e["amount"]
        else:
            remaining.append(e)
    if settled > 0:
        profile["cash"] = round(profile["cash"] + settled, 2)
        profile["unsettled_entries"] = remaining
        profile["unsettled_cash"] = round(sum(e["amount"] for e in remaining), 2)
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
        redirect_uri = get_dynamic_redirect_uri(ui.context.client.request)
        login_url = get_auth_url(redirect_uri=redirect_uri)
        with ui.column().classes('items-center justify-center min-h-screen gap-6'):
            ui.label('📈').classes('text-6xl')
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
        profile = {"name": name, "cash": 1000.0, "holdings": {}, "alerts": [], "history": [],
                   "unsettled_cash": 0.0, "unsettled_entries": [], "dividend_tracker": {},
                   "total_dividends_earned": 0.0}
        _save(email, profile)
    profile["name"] = name
    profile.setdefault("total_dividends_earned", 0.0)

    # Warm price cache for current user's holdings and alerts (not the entire class)
    try:
        tickers_to_warm = set()
        for t in profile.get('holdings', {}).keys():
            tickers_to_warm.add(t)
        for a in profile.get('alerts', []):
            tickers_to_warm.add(a['ticker'])
        if tickers_to_warm:
            warm_price_cache(list(tickers_to_warm))
    except Exception as e:
        logger.error(f"Error warming price cache: {e}")

    profile = _process_settlement(email, profile)
    deposit_amt, deposit_weeks = _process_weekly(email, profile)
    profile = _process_dividends(email, profile)
    triggered = _check_alerts(profile)

    # ── UI ──
    ui.query('body').classes('bg-gray-50')
    ui.add_head_html(
        '<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>',
        shared=True,
    )

    # Topbar
    with ui.header().classes('bg-white/70 backdrop-blur-lg border-b border-gray-200'):
        with ui.row().classes('w-full items-center justify-between px-6 py-3'):
            ui.label('📈 Math Finance Simulator').classes('text-lg font-bold text-gray-800')
            with ui.row().classes('items-center').style('overflow: hidden;'):
                ui.icon('account_circle').props('size=sm').classes('text-gray-500')
                ui.label(f'{name}').style('font-size: 0.875rem; color: #4b5563; margin-left: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px;')
                ui.label(f'({email})').style('font-size: 0.75rem; color: #9ca3af; margin-left: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 150px;')

    # Summary bar
    @ui.refreshable
    def summary():
        p = _portfolio(profile)
        cls = 'text-green-600' if p['pl'] >= 0 else 'text-red-500'
        sign = '+' if p['pl'] >= 0 else ''
        rows = [
            ("Cash Balance", f"${p['cash']:,.2f}", 'text-gray-900'),
            ("Unsettled Cash", f"${p['unsettled']:,.2f}", 'text-amber-500'),
            ("Portfolio Value", f"${p['total_hold']:,.2f}", 'text-gray-900'),
            ("Dividends Earned", f"${profile.get('total_dividends_earned', 0.0):,.2f}", 'text-green-600'),
            ("Total Account", f"${p['total']:,.2f}", 'text-gray-900'),
        ]
        with ui.row().style('width: 100%; gap: 0; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.06); border-bottom: 1px solid #e5e7eb; padding: 1rem 1.5rem;'):
            for label, val, color in rows:
                with ui.column().style('flex: 1; min-width: 0;'):
                    ui.label(label).classes('text-xs text-gray-400 uppercase tracking-wider font-medium')
                    ui.label(val).classes(f'text-xl font-bold {color}')
                    if label == "Portfolio Value":
                        ui.label(f"{sign}${p['pl']:,.2f} ({p['pl_pct']:+.2f}%)"
                                ).classes(f'text-xs font-semibold {cls}')

    summary()

    if deposit_amt:
        with ui.row().classes('bg-green-50 border border-green-200 rounded-lg px-4 py-2 mx-6 mt-2'):
            ui.label(f'💰 Weekly deposit: +${deposit_amt:.2f} ({deposit_weeks} week{"s" if deposit_weeks > 1 else ""})'
                    ).classes('text-green-700 text-sm font-medium')

    if triggered:
        for msg in triggered:
            with ui.row().classes('bg-amber-50 border border-amber-200 rounded-lg px-4 py-2 mx-6 mt-2'):
                ui.label(f'🔔 {msg}').classes('text-amber-700 text-sm font-medium')

    # Tabs
    with ui.tabs().classes('w-full border-b border-gray-200 bg-white sticky top-0 z-10') as tabs:
        tp = ui.tab('📋 Portfolio')
        tt = ui.tab('🪙 Trade')
        tr = ui.tab('🔬 Research')
        ta = ui.tab('🔔 Alerts')
        ts = ui.tab('🏆 Standings')

    with ui.tab_panels(tabs).classes('w-full max-w-7xl mx-auto px-4'):
        # ── PORTFOLIO ────────────────────────────────────
        with ui.tab_panel(tp):
            @ui.refreshable
            def portfolio_content():
                p = _portfolio(profile)
                holdings = p['holdings']
                intl = {"VWO","VEA","EFA","IEMG","FXI","EWJ","EWG","EWZ",
                        "INDA","KWEB","EEM","FLTW","TAN","ICLN"}
                l1, v1, c1 = [], [], []
                if p['cash'] >= 0:
                    l1.append("Cash"); v1.append(p['cash']); c1.append("#3b82f6")
                if p['unsettled'] > 0:
                    l1.append("Unsettled"); v1.append(p['unsettled']); c1.append("#f59e0b")
                us = itnl = 0.0
                for t, pos in list(holdings.items()):
                    pr, _, _ = fetch_stock_market_data(t)
                    if pr is not None:
                        mv = pos['shares'] * pr
                        if t.upper() in intl: itnl += mv
                        else: us += mv
                if us > 0: l1.append("US"); v1.append(us); c1.append("#10b981")
                if itnl > 0: l1.append("International"); v1.append(itnl); c1.append("#8b5cf6")

                sl, sv, sc = [], [], []
                palette = ["#3b82f6","#f59e0b","#10b981","#8b5cf6","#f43f5e","#6366f1",
                           "#ec4899","#14b8a6","#f97316","#06b6d4"]
                for i, t in enumerate(holdings):
                    pr, _, _ = fetch_stock_market_data(t)
                    if pr is not None:
                        sv.append(holdings[t]['shares'] * pr)
                        sl.append(t); sc.append(palette[i % len(palette)])

                if l1 or sl:
                    with ui.row().style('width: 100%; gap: 1rem;'):
                        if l1:
                            fig = go.Figure(data=[go.Pie(labels=l1, values=v1, hole=0.4,
                                marker=dict(colors=c1, line=dict(color='white', width=2)),
                                textinfo='label+percent', textposition='auto', textfont=dict(size=10))])
                            fig.update_layout(height=240, margin=dict(l=0,r=0,t=0,b=0),
                                              showlegend=False, paper_bgcolor='rgba(0,0,0,0)')
                            with ui.column().style('flex: 1; width: 100%; align-items: center; justify-content: center;'): ui.plotly(fig).style('width: 100%; height: 240px')
                        if sl:
                            fig = go.Figure(data=[go.Pie(labels=sl, values=sv, hole=0.4,
                                marker=dict(colors=sc, line=dict(color='white', width=2)),
                                textinfo='label+percent', textposition='auto', textfont=dict(size=10))])
                            fig.update_layout(height=240, margin=dict(l=0,r=0,t=0,b=0),
                                              showlegend=False, paper_bgcolor='rgba(0,0,0,0)')
                            with ui.column().style('flex: 1; width: 100%; align-items: center; justify-content: center;'): ui.plotly(fig).style('width: 100%; height: 240px')

                with ui.card().classes('w-full p-4 mt-4'):
                    ui.label('Positions').classes('font-bold text-lg mb-2')
                    if p['live_data']:
                        df = pd.DataFrame(p['live_data'])
                        raw = df['Return'].copy()
                        df['Return'] = df['Return'].map("{:+.2f}%".format)
                        t = ui.table.from_pandas(df).classes('w-full')
                        t.add_slot('body-cell-Value', '''
                            <td style="text-align:right;vertical-align:middle">
                                {{ props.row.Value }}
                            </td>
                        ''')
                        t.add_slot('body-cell-Return', '''
                            <td style="vertical-align:middle" :class="props.row.Return && props.row.Return.startsWith('-') ? 'text-red-500 font-semibold text-right' : 'text-green-600 font-semibold text-right'">
                                {{ props.row.Return }}
                            </td>
                        ''')
                    else:
                        ui.label('No open positions.').classes('text-gray-400')

                if p['history']:
                    with ui.card().classes('w-full p-4 mt-4'):
                        ui.label('Trade History').classes('font-bold text-lg mb-2')
                        ui.table.from_pandas(pd.DataFrame(reversed(p['history']))).classes('w-full')

            portfolio_content()

        # ── TRADE ────────────────────────────────────────
        with ui.tab_panel(tt):
            pending = {'data': None}
            opts = {t: format_ticker_option(t) for t in ALL_TICKERS}
            sel = ui.select(options=opts, label='Search symbol', clearable=True).classes('w-full').props('use-input input-debounce=300')

            price_val = ui.label().classes('text-xl font-bold text-gray-900')
            price_sub = ui.label().classes('text-sm text-gray-500')
            action = ui.radio(['Buy', 'Sell'], value='Buy').props('inline dense').classes('mt-1')
            mode = ui.radio(['Shares', 'Amount ($)'], value='Shares').props('inline dense')
            shares_in = ui.number(label='Shares', value=1.0, min=0.001, step=0.1, format='%.4f').classes('w-full')
            amount_in = ui.number(label='Amount ($)', value=100.0, min=1.0, step=10.0).classes('w-full')
            amount_in.set_visibility(False)
            preview = ui.label().classes('text-sm text-gray-500 mt-1')

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
                c_pct = (cost / profile['cash']) * 100 if profile['cash'] > 0 else 0
                p = _portfolio(profile)
                if action.value == 'Buy':
                    ex = profile['holdings'].get(t, {}).get('shares', 0)
                    w = ((cost + (ex * pr)) / p['total']) * 100 if p['total'] > 0 else 0
                    preview.set_text(f'≈ ${cost:,.2f}  ·  {c_pct:.1f}% of cash  ·  est. weight {w:.1f}%')
                else:
                    if t in profile['holdings']:
                        rm = max(profile['holdings'][t]['shares'] - shares_in.value, 0)
                        w = ((rm * pr) / p['total']) * 100 if p['total'] > 0 else 0
                        preview.set_text(f'≈ {shares_in.value:.4f} shares  ·  est. new weight {w:.1f}%')

            sel.on('change', _upd_sel); sel.on('change', _upd_preview)
            action.on('change', _upd_preview); mode.on('change', _upd_preview)
            mode.on('change', _upd_mode)
            shares_in.on('change', _upd_preview); amount_in.on('change', _upd_preview)

            @ui.refreshable
            def confirm_card():
                d = pending['data']
                if not d: return
                with ui.card().classes('w-full bg-blue-50 border-2 border-blue-200 p-4 mt-3'):
                    ui.label(f"Confirm {d['action']}: {d['shares']:.4f} shares of {d['ticker']} "
                             f"at ${d['price']:.2f} = ${d['cost']:.2f}").classes('font-semibold text-blue-900')
                    with ui.row().classes('gap-3 mt-3'):
                        ui.button(f"✅ Confirm {d['action']}", on_click=lambda: _exec(d)
                                 ).props('color=primary').classes('bg-blue-600 text-white')
                        ui.button('❌ Cancel', on_click=lambda: (pending.update({'data': None}), confirm_card.refresh()))

            def _exec(data):
                t = data['ticker']
                if data['action'] == 'Buy':
                    profile['cash'] = round(profile['cash'] - data['cost'], 2)
                    if t in profile['holdings']:
                        profile['holdings'][t]['shares'] += data['shares']
                        profile['holdings'][t]['total_cost'] += data['cost']
                    else:
                        profile['holdings'][t] = {'shares': data['shares'], 'total_cost': data['cost']}
                    profile.setdefault('history', []).append({
                        'type': 'Buy', 'ticker': t, 'shares': round(data['shares'], 4),
                        'price': round(data['price'], 2), 'total': round(data['cost'], 2),
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M')})
                else:
                    owned = profile['holdings'][t]['shares']
                    frac = data['shares'] / owned
                    cb = frac * profile['holdings'][t]['total_cost']
                    profit = data['cost'] - cb; tax = max(0, round(profit * 0.15, 2))
                    net = data['cost'] - tax
                    profile['unsettled_cash'] = round(profile.get('unsettled_cash', 0.0) + net, 2)
                    profile.setdefault('unsettled_entries', []).append({
                        'amount': net, 'time': datetime.now().isoformat()})
                    profile['holdings'][t]['shares'] -= data['shares']
                    profile['holdings'][t]['total_cost'] -= cb
                    if profile['holdings'][t]['shares'] < 0.0001: del profile['holdings'][t]
                    profile.setdefault('history', []).append({
                        'type': 'Sell', 'ticker': t, 'shares': round(data['shares'], 4),
                        'price': round(data['price'], 2), 'total': round(data['cost'], 2),
                        'time': datetime.now().strftime('%Y-%m-%d %H:%M')})
                _save(email, profile)
                pending['data'] = None
                confirm_card.refresh()
                summary.refresh(); portfolio_content.refresh()
                movers.refresh(); standings_content.refresh()
                ui.notify('✅ Trade executed!', type='positive')

            def _review():
                t = sel.value
                if not t: ui.notify('Select a ticker', type='warning'); return
                pr, _, _ = fetch_stock_market_data(t)
                if pr is None: ui.notify(f'Price unavailable for {t}', type='negative'); return
                cost = (shares_in.value * pr) if mode.value == 'Shares' else amount_in.value
                sh = (shares_in.value if mode.value == 'Shares' else cost / pr)
                a = action.value
                err = None
                if a == 'Buy' and cost > profile['cash']:
                    err = f'Insufficient cash (${profile["cash"]:.2f} available, ${cost:.2f} needed)'
                elif a == 'Sell':
                    if t not in profile['holdings']: err = 'Not owned.'
                    else:
                        o = profile['holdings'][t]['shares']
                        if mode.value == 'Shares' and sh > o + 0.0001: err = f'Only {o:.4f} shares owned.'
                        elif mode.value == 'Amount ($)' and cost > o * pr + 0.01: err = 'Exceeds position value.'
                if err: ui.notify(err, type='negative'); return
                pending['data'] = {'action': a, 'ticker': t, 'shares': sh, 'cost': cost, 'price': pr}
                confirm_card.refresh()

            # Layout
            with ui.row().style('width: 100%; gap: 1rem;'):
                with ui.card().style('flex: 1; padding: 1rem;'):
                    ui.label('Trade Ticket').classes('font-bold text-lg mb-3')
                    sel
                    with ui.row().classes('items-baseline gap-2 mt-1'):
                        price_val; price_sub
                    action
                    mode
                    shares_in; amount_in
                    preview
                    ui.button('📋 Review Order', on_click=_review).props('color=primary').classes('w-full mt-2')
                    confirm_card()

                with ui.card().style('flex: 1; padding: 1rem;'):
                    ui.label('📊 Market Movers').classes('font-bold text-lg mb-3')
                    @ui.refreshable
                    def movers():
                        for label, items in [("Stock Gainers", get_top_movers(tuple(STOCK_TICKERS))),
                                             ("ETF Gainers", get_top_movers(tuple(ETF_TICKERS)))]:
                            gainers = [x for x in items if x[3] > 0][:5]
                            losers = [x for x in items if x[3] < 0][-5:][::-1]
                            if not gainers and not losers:
                                ui.label(f'{label}: No data').classes('text-gray-400 text-xs'); continue
                            with ui.column().classes('w-full gap-1 mb-3'):
                                if gainers:
                                    ui.label(f'{label} ↑').classes('text-xs font-semibold text-green-600')
                                    for t, n, p, c in gainers:
                                        with ui.row().classes('w-full items-center justify-between bg-green-50 rounded-lg px-3 py-1.5'):
                                            ui.label(f'{t}').classes('text-xs font-bold text-gray-800 w-14')
                                            ui.label(n[:18]).classes('text-xs text-gray-500 flex-1 truncate')
                                            ui.label(f'${p:.2f}').classes('text-xs text-gray-700 w-16 text-right')
                                            ui.label(f'{c:+.2f}%').classes(f'text-xs font-semibold w-16 text-right text-green-600')
                                if losers:
                                    ui.label(f'{label} ↓').classes('text-xs font-semibold text-red-500 mt-1')
                                    for t, n, p, c in losers:
                                        with ui.row().classes('w-full items-center justify-between bg-red-50 rounded-lg px-3 py-1.5'):
                                            ui.label(t).classes('text-xs font-bold text-gray-800 w-14')
                                            ui.label(n[:18]).classes('text-xs text-gray-500 flex-1 truncate')
                                            ui.label(f'${p:.2f}').classes('text-xs text-gray-700 w-16 text-right')
                                            ui.label(f'{c:+.2f}%').classes(f'text-xs font-semibold w-16 text-right text-red-500')
                            ui.separator().classes('my-1')
                    movers()

        # ── RESEARCH ─────────────────────────────────────
        with ui.tab_panel(tr):
            with ui.row().style('width: 100%; gap: 1rem;'):
                with ui.card().style('width: 33%; padding: 1rem;'):
                    ui.label('Volatility Calculator').classes('font-bold text-lg mb-3')
                    vs = ui.select(options=opts, label='Search symbol', clearable=True).classes('w-full').props('use-input input-debounce=300')
                    vp = ui.select(options=CHART_PERIODS, value='3mo', label='Period').classes('w-full')
                    v_std = ui.label('—').classes('text-2xl font-bold')
                    v_range = ui.label('—').classes('text-2xl font-bold')
                    v_desc = ui.label('Pick a stock to calculate volatility.').classes('text-sm text-gray-500 mt-2')

                    def _vol():
                        t = vs.value
                        if not t: v_std.set_text('—'); v_range.set_text('—'); v_desc.set_text('Pick a stock.'); return
                        import yfinance as yf
                        from utils.market import _flatten_cols
                        try:
                            d = _flatten_cols(yf.download(t, period=vp.value, progress=False))
                            if d is None or len(d) < 2:
                                v_std.set_text('N/A'); v_range.set_text('N/A'); v_desc.set_text('Not enough data.'); return
                            d['chg'] = d['Close'].pct_change() * 100
                            std = d[['Close', 'chg']].dropna()['chg'].std()
                            pl = CHART_PERIODS.get(vp.value, vp.value).lower()
                            risk = 'very low' if std < 0.5 else 'low' if std < 1.0 else 'moderate' if std < 1.5 else 'high' if std < 2.5 else 'very high'
                            v_std.set_text(f'{std:.2f}%'); v_range.set_text(f'±{std:.2f}%')
                            v_desc.set_text(f'Over {pl}, {t} typically moves ±{std:.1f}% per day. Risk: {risk}.')
                        except Exception:
                            v_std.set_text('N/A'); v_range.set_text('N/A'); v_desc.set_text('Error fetching data.')
                    vs.on('change', _vol); vp.on('change', _vol)

                    with ui.row().classes('w-full gap-2 mt-2'):
                        with ui.column().classes('flex-1 bg-gray-50 rounded-lg p-3'):
                            ui.label('Daily Volatility').classes('text-xs text-gray-400 uppercase tracking-wider font-medium')
                            v_std
                        with ui.column().classes('flex-1 bg-gray-50 rounded-lg p-3'):
                            ui.label('Typical Range').classes('text-xs text-gray-400 uppercase tracking-wider font-medium')
                            v_range
                    v_desc

                with ui.card().style('flex: 1; padding: 1rem;'):
                    ui.label('Price History').classes('font-bold text-lg mb-3')
                    cp_sel = ui.select(options=CHART_PERIODS, value='3mo', label='Period').classes('w-40')
                    cs_sel = ui.select(options={'Line': 'Line', 'Candlestick': 'Candlestick'}, value='Line', label='Style').classes('w-36')
                    chart_price = ui.label().classes('text-3xl font-bold')
                    chart_sub = ui.label().classes('text-sm text-gray-500')
                    ui.html('<div id="tvchart" style="width:100%;height:380px"></div>', sanitize=False)

                    ui.run_javascript('''
if (!window.__tv) {
    window.__tv = {};
    var c = LightweightCharts.createChart(document.getElementById('tvchart'), {
        layout: { textColor: '#1f2937', fontFamily: "'Inter',-apple-system,sans-serif", fontSize: 12 },
        grid: { vertLines: { color: 'rgba(128,128,128,0.1)' }, horzLines: { color: 'rgba(128,128,128,0.1)' } },
        timeScale: { borderColor: 'rgba(128,128,128,0.2)', timeVisible: false },
        rightPriceScale: { borderColor: 'rgba(128,128,128,0.2)' },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        handleScroll: false, handleScale: false,
    });
    window.__tv.chart = c;
    window.__tv.candle = c.addCandlestickSeries({
        upColor: '#10b981', downColor: '#f43f5e',
        borderUpColor: '#10b981', borderDownColor: '#f43f5e',
        wickUpColor: '#10b981', wickDownColor: '#f43f5e',
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });
    window.__tv.line = c.addLineSeries({
        color: '#3b82f6', lineWidth: 2,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });
}
                    ''')

                    def _chart():
                        t = vs.value
                        if not t:
                            chart_price.set_text(''); chart_sub.set_text('')
                            return
                        pr, _, company = fetch_stock_market_data(t)
                        chart_price.set_text(f'${pr:.2f}' if pr else '')
                        chart_sub.set_text(company if pr else '')
                        period = cp_sel.value
                        style = cs_sel.value
                        hist = fetch_full_history(t, period=period)
                        if hist is None or len(hist) <= 5:
                            ui.run_javascript(
                                'window.__tv.candle.setData([]);window.__tv.line.setData([]);')
                            return

                        data = []
                        for idx, row in hist.iterrows():
                            data.append({
                                'time': int(idx.timestamp()),
                                'open': float(row['Open']),
                                'high': float(row['High']),
                                'low': float(row['Low']),
                                'close': float(row['Close']),
                            })
                        line_data = [{'time': d['time'], 'value': d['close']} for d in data]
                        candle_vis = 'true' if style == 'Candlestick' else 'false'
                        line_vis = 'true' if style == 'Line' else 'false'
                        ui.run_javascript(f'''
window.__tv.candle.setData({json.dumps(data)});
window.__tv.line.setData({json.dumps(line_data)});
window.__tv.candle.applyOptions({{visible: {candle_vis}}});
window.__tv.line.applyOptions({{visible: {line_vis}}});
window.__tv.chart.timeScale().fitContent();
                        ''')

                    cp_sel.on('change', _chart)
                    cs_sel.on('change', _chart)
                    vs.on('change', _chart)

        # ── ALERTS ───────────────────────────────────────
        with ui.tab_panel(ta):
            with ui.card().classes('w-full p-4'):
                ui.label('Price Alerts').classes('font-bold text-lg mb-2')
                ui.label('Notify when a stock crosses a target price.').classes('text-sm text-gray-500 mb-3')
                asel = ui.select(options=opts, label='Search symbol', clearable=True).classes('w-56').props('use-input input-debounce=300')
                adir = ui.select(options={'above': 'Above', 'below': 'Below'}, value='above').classes('w-32')
                apr = ui.number(label='Target Price', value=200.0, min=0.01, step=1.0).classes('w-32')

                @ui.refreshable
                def alert_list():
                    for i, a in enumerate(profile.get('alerts', [])):
                        with ui.row().classes('items-center gap-3 py-2 border-b border-gray-100'):
                            ui.label(a['ticker']).classes('font-semibold w-20')
                            ui.label(f"→ {a['direction']}").classes('text-gray-500 w-20 text-sm')
                            ui.label(f"${a['price']:.2f}").classes('w-20 text-sm')
                            ui.button('✕', on_click=lambda idx=i: _del(idx)).props('flat dense color=negative')

                def _add():
                    t = asel.value
                    if not t: ui.notify('Select a ticker', type='warning'); return
                    profile.setdefault('alerts', []).append({'ticker': t, 'direction': adir.value, 'price': apr.value})
                    _save(email, profile); alert_list.refresh(); ui.notify('Alert added!', type='positive')

                def _del(idx):
                    profile.get('alerts', []).pop(idx); _save(email, profile); alert_list.refresh()

                with ui.row().classes('items-center gap-2'):
                    asel; adir; apr
                    ui.button('+ Add', on_click=_add).props('color=primary').classes('bg-blue-600 text-white')
                alert_list()

        # ── STANDINGS ────────────────────────────────────
        with ui.tab_panel(ts):
            with ui.card().classes('w-full p-4'):
                ui.label('🏆 Classroom Standings').classes('font-bold text-lg mb-3')
                @ui.refreshable
                def standings_content():
                    db = get_gcs_database()
                    if not db: ui.label('Could not load standings.').classes('text-gray-500'); return
                    rows = []
                    for e, p in db.items():
                        if e == 'rpiana@stjohnsguam.com': continue
                        mv = 0.0
                        for t, pos in p.get('holdings', {}).items():
                            pr, _, _ = fetch_stock_market_data(t)
                            if pr is not None: mv += pos['shares'] * pr
                        nw = p.get('cash', 1000.0) + mv
                        rows.append({'Student': p.get('name', 'Student'), 'Net Worth': nw, 'Return': ((nw-1000)/1000)*100})
                    if not rows: ui.label('No participants.').classes('text-gray-500'); return
                    df = pd.DataFrame(rows).sort_values('Net Worth', ascending=False).reset_index(drop=True)
                    df['Rank'] = df.index + 1
                    df['Net Worth'] = df['Net Worth'].map('${:,.2f}'.format)
                    df['Return'] = df['Return'].map('{:+.2f}%'.format)
                    ui.table.from_pandas(df[['Rank', 'Student', 'Net Worth', 'Return']]).classes('w-full')
                standings_content()

    # ── Teacher admin ─────────────────────────────────────
    if is_teacher(email):
        with ui.card().classes('w-full max-w-7xl mx-auto px-4 p-4 mt-4 border-t-2 border-blue-200'):
            ui.label('👨‍🏫 Teacher Administration').classes('font-bold text-lg mb-2')
            with ui.tabs().classes('w-full') as at:
                a1 = ui.tab('📊 Class Portfolio Data')
                a2 = ui.tab('🧪 Sandbox')

            with ui.tab_panels(at):
                with ui.tab_panel(a1):
                    @ui.refreshable
                    def admin_table():
                        db = get_gcs_database()
                        if not db: ui.label('No student accounts.').classes('text-gray-500'); return
                        rows = []
                        for e, p in db.items():
                            if e == 'rpiana@stjohnsguam.com': continue
                            mv = 0.0
                            for t, pos in p.get('holdings', {}).items():
                                pr, _, _ = fetch_stock_market_data(t)
                                if pr is not None: mv += pos['shares'] * pr
                            nw = p.get('cash', 1000.0) + mv
                            pl = nw - 1000.0
                            rows.append({'Student': p.get('name', 'Unknown'), 'Email': e.split('@')[0],
                                         'Net Worth': nw, 'P&L': pl, 'Return': (pl/1000)*100,
                                         'Cash': p.get('cash', 1000.0), 'Stock Value': mv,
                                         'Trades': len(p.get('history', []))})
                        if not rows: ui.label('No records.').classes('text-gray-500'); return
                        df = pd.DataFrame(rows).sort_values('Net Worth', ascending=False).reset_index(drop=True)
                        df['Rank'] = df.index + 1
                        for c in ['Net Worth', 'P&L', 'Cash', 'Stock Value']:
                            df[c] = df[c].map('${:,.2f}'.format)
                        df['Return'] = df['Return'].map('{:+.2f}%'.format)
                        ui.table.from_pandas(df).classes('w-full')
                        ui.label(f'Active: {len(df)}').classes('text-sm text-gray-500 mt-2')
                    admin_table()

                with ui.tab_panel(a2):
                    ui.label('🧪 Your Sandbox Status').classes('font-semibold')
                    ui.label('Personal trading in main tabs, filtered from standings.'
                            ).classes('text-sm text-gray-500')
                    ui.json_editor(properties={
                        'Name': profile.get('name'),
                        'Cash': f"${profile.get('cash', 0.0):,.2f}",
                        'Holdings': {t: p['shares'] for t, p in profile.get('holdings', {}).items()},
                        'Trades': len(profile.get('history', []))
                    })

    # ── Periodic refresh ──
    def _tick():
        summary.refresh(); portfolio_content.refresh(); standings_content.refresh()
    ui.timer(300, _tick, active=True)

# ── CSS ──────────────────────────────────────────────────
ui.add_css("""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
* { font-family: 'Inter', -apple-system, sans-serif !important; }
body { background: #f8fafc; }
.q-header { box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.q-tab--active { color: #2563eb !important; font-weight: 600; }
.q-table th { font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; color: #64748b; }
.q-table td { font-size: 0.875rem; }
.q-card { border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); transition: box-shadow 0.2s; }
.q-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.q-btn { border-radius: 8px; font-weight: 600; transition: all 0.15s; }
.q-btn:hover { transform: translateY(-1px); }
@media (max-width: 640px) {
  .q-header .q-btn { font-size: 0.8rem; padding: 0.4rem 0.8rem; }
  .q-table { font-size: 0.75rem; }
}
.q-table td { vertical-align: middle; }
""", shared=True)

# ── Startup ──────────────────────────────────────────────
ui.run(
    title='Math Finance Simulator',
    host='0.0.0.0',
    port=int(os.environ.get('PORT', 8080)),
    storage_secret=os.environ.get('STORAGE_SECRET', 'dev-secret-change-me'),
)
