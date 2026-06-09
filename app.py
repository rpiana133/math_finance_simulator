import streamlit as st
import pandas as pd
import json
from datetime import datetime
import plotly.graph_objects as go

from utils.auth import init_auth_state, handle_legal_pages, get_client_config, handle_redirect, do_login
from utils.storage import load_student_profile, save_student_profile, get_gcs_database
from utils.market import fetch_stock_market_data, fetch_full_history, get_dividends, stock_picker, CHART_PERIODS, STOCK_TICKERS, ETF_TICKERS, get_top_movers
from utils.charts import plot_candlestick

# Page Configuration
st.set_page_config(page_title="Classroom Stock Simulator", page_icon="📈", layout="wide")

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; }
    
    /* Variables for light/dark mode */
    :root {
        --bg-glass: rgba(255, 255, 255, 0.7);
        --bg-card: #ffffff;
        --border-color: #e2e8f0;
        --text-main: #0f172a;
        --text-muted: #64748b;
        --accent-blue: #3b82f6;
        --accent-green: #10b981;
        --accent-red: #f43f5e;
        --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
        --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
    }
    
    [data-theme="dark"] {
        --bg-glass: rgba(30, 41, 59, 0.7);
        --bg-card: #1e293b;
        --border-color: #334155;
        --text-main: #f8fafc;
        --text-muted: #94a3b8;
        --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.3);
        --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.4), 0 2px 4px -2px rgb(0 0 0 / 0.4);
    }

    .stApp { background-color: transparent; }

    p, li, .markdown-text-container, .stMarkdown, .stWrite, div {
        color: var(--text-main);
    }
    
    /* Top nav bar */
    .topbar {
        background: var(--bg-glass);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        padding: 0.75rem 1.5rem;
        border-radius: 12px;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border: 1px solid var(--border-color);
        box-shadow: var(--shadow-sm);
    }
    .topbar h1 { margin:0; font-size:1.3rem; font-weight:700; letter-spacing:-0.5px; }
    .topbar .user-badge {
        display:flex; align-items:center; gap:8px;
        background: var(--bg-card); padding: 6px 16px; border-radius: 20px;
        font-size:0.85rem; border: 1px solid var(--border-color);
        box-shadow: var(--shadow-sm);
    }
    
    /* Portfolio summary bar */
    .psummary {
        display: flex; gap: 2rem; margin-bottom: 1.2rem;
        background: var(--bg-card); padding: 1.25rem 1.5rem; border-radius: 12px;
        border: 1px solid var(--border-color);
        box-shadow: var(--shadow-md);
        flex-wrap: wrap;
    }
    .psummary .label { font-size:0.75rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.5px; font-weight:600; }
    .psummary .value { font-size:1.5rem; font-weight:700; }
    .psummary .value.positive { color:var(--accent-green); }
    .psummary .value.negative { color:var(--accent-red); }
    .psummary .sub { font-size:0.85rem; font-weight:600; margin-top:2px; }
    .psummary .sub.positive { color:var(--accent-green); }
    .psummary .sub.negative { color:var(--accent-red); }
    
    /* Cards */
    .card {
        background: var(--bg-card); border-radius: 12px; padding: 1.5rem;
        border: 1px solid var(--border-color); margin-bottom: 1rem;
        box-shadow: var(--shadow-sm);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .card:hover {
        box-shadow: var(--shadow-md);
    }
    .card h3 { margin:0 0 1rem 0; font-size:1.1rem; font-weight:700; }
    
    /* Metric boxes */
    .metric-row { display:flex; gap:1rem; margin-bottom:1rem; }
    .metric-box {
        background: var(--bg-glass); border-radius:10px; padding:1rem; flex:1;
        border: 1px solid var(--border-color);
    }
    .metric-box .m-label { font-size:0.75rem; color:var(--text-muted); text-transform:uppercase; font-weight:600; letter-spacing:0.3px; }
    .metric-box .m-value { font-size:1.2rem; font-weight:700; margin-top:4px; }
    
    /* Buttons */
    .stButton button {
        font-weight:600; border-radius:8px; font-size:0.9rem;
        transition: all 0.2s ease; 
    }
    .stButton button:hover { transform: translateY(-1px); box-shadow: var(--shadow-md); }
    .stButton button:active { transform:scale(0.98); }
    
    /* Alert Animation */
    @keyframes pulse-ring {
        0% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4); }
        70% { box-shadow: 0 0 0 10px rgba(245, 158, 11, 0); }
        100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
    }
    .stAlert { border-radius: 8px; border: 1px solid var(--border-color); animation: pulse-ring 2s infinite; }

    /* Data table overrides to adapt to theme */
    [data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

    /* Hide default streamlit header */
    #MainMenu {visibility:hidden;} footer {visibility:hidden;}
</style>
"""

# ==========================================
# 1. INIT AUTHENTICATION
# ==========================================
init_auth_state()
handle_legal_pages()

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
# 2. LOAD DATA
# ==========================================
student_email = st.session_state.user_info['email']
student_profile = load_student_profile(student_email)

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

# Settle proceeds older than 24 hours
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

student_cash = student_profile["cash"]

# Dividend auto-credit
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

student_cash = student_profile["cash"]

# ==========================================
# 3. STOCK DATA COMPUTATION
# ==========================================
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

# Alerts
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

# ==========================================
# 4. USER INTERFACE
# ==========================================
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Top nav bar
st.markdown(f"""
<div class="topbar">
    <h1>📈 Math Finance Simulator</h1>
    <div class="user-badge">
        <span>👤 {student_profile['name']}</span>
        <span style="opacity:0.6">|</span>
        <span style="font-size:0.8rem; color:var(--text-muted);">{student_email}</span>
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
        <div class="sub">settles in &lt;24h</div>
    </div>
    <div class="item">
        <div class="label">Portfolio Value</div>
        <div class="value">${total_holding_value:,.2f}</div>
        <div class="sub {pl_class}">{"+" if stock_pl_dollars >= 0 else ""}${stock_pl_dollars:,.2f} ({stock_pl_pct:+.2f}%)</div>
    </div>
    <div class="item">
        <div class="label">Dividends Earned</div>
        <div class="value" style="color:#10b981;">${student_profile.get("total_dividends_earned", 0.0):,.2f}</div>
    </div>
    <div class="item">
        <div class="label">Total Account</div>
        <div class="value">${total_portfolio_value:,.2f}</div>
    </div>
</div>
""", unsafe_allow_html=True)

if triggered_alerts:
    for alert_msg in triggered_alerts:
        st.warning(f"🔔 {alert_msg}")

main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs(["📋 Portfolio", "🪙 Trade", "🔬 Research", "🔔 Alerts", "🏆 Standings"])

with main_tab1:
    labels = []
    values = []
    colors = []
    if student_cash > 0:
        labels.append("Cash")
        values.append(student_cash)
        colors.append("#3b82f6")
    if student_unsettled > 0:
        labels.append("Unsettled")
        values.append(student_unsettled)
        colors.append("#f59e0b")
    
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
        colors.append("#10b981")
    if intl_value > 0:
        labels.append("International")
        values.append(intl_value)
        colors.append("#8b5cf6")
        
    stock_labels = []
    stock_values = []
    stock_colors = []
    palette = ["#3b82f6", "#f59e0b", "#10b981", "#8b5cf6", "#f43f5e", "#6366f1",
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
                                              marker=dict(colors=colors, line=dict(color='rgba(0,0,0,0)', width=1)),
                                              textinfo='label+percent', textposition='outside',
                                              textfont=dict(size=11))])
                fig.update_layout(height=280, margin=dict(l=0, r=0, t=0, b=0),
                                  showlegend=False, paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig, use_container_width=True, key="portfolio_pie")
        if stock_values:
            with cols[1]:
                fig2 = go.Figure(data=[go.Pie(labels=stock_labels, values=stock_values, hole=0.4,
                                               marker=dict(colors=stock_colors, line=dict(color='rgba(0,0,0,0)', width=1)),
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
            return ["color: #10b981" if r >= 0 else "color: #f43f5e"
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
            <div style="margin:-0.5rem 0 0.5rem 0; font-size:0.85rem; color:var(--text-muted);">
                {company} · <strong>${live_price:.2f}</strong>
            </div>
            """, unsafe_allow_html=True)
        else:
            if trade_ticker:
                st.warning(f"Price unavailable for {trade_ticker}")
        
        action = st.radio("Action", ["Buy", "Sell"], horizontal=True)
        order_mode = st.radio("Order Type", ["By Shares", "By Amount ($)"], horizontal=True)
        
        actual_cost = 0.0
        shares_to_trade = 0.0
        
        if order_mode == "By Shares":
            shares_input = st.number_input("Shares", min_value=0.001, value=1.0, step=0.1, format="%.4f")
            usd_allocation = shares_input * live_price if live_price else 0
            if live_price:
                actual_cost = usd_allocation
                shares_to_trade = shares_input
        else:
            usd_allocation = st.number_input("Amount ($)", min_value=1.00, value=100.00, step=10.00)
            if live_price:
                shares_to_trade = usd_allocation / live_price
                actual_cost = usd_allocation

        if live_price:
            cash_used_pct = (actual_cost / student_cash) * 100 if student_cash > 0 else 0
            new_port_val = total_portfolio_value
            if action == "Buy":
                post_trade_weight = ((actual_cost + (student_holdings.get(trade_ticker, {}).get('shares', 0) * live_price)) / new_port_val) * 100 if new_port_val > 0 else 0
                st.caption(f"≈ **${actual_cost:,.2f}** ({cash_used_pct:.1f}% of cash) &rarr; Est. Portfolio Weight: **{post_trade_weight:.1f}%**")
            elif action == "Sell":
                if trade_ticker in student_holdings:
                    rem_shares = student_holdings[trade_ticker]['shares'] - shares_to_trade
                    post_trade_weight = ((max(rem_shares, 0) * live_price) / new_port_val) * 100 if new_port_val > 0 else 0
                    st.caption(f"≈ **{shares_to_trade:.4f} shares** &rarr; Est. New Weight: **{post_trade_weight:.1f}%**")
                else:
                    st.caption(f"≈ **{shares_to_trade:.4f} shares**")

        if trade_ticker and st.button("📋 Review Order", type="primary", use_container_width=True):
            if live_price is None:
                st.error(f"Ticker '{trade_ticker}' not found.")
            else:
                error = None
                if action == "Buy" and actual_cost > student_cash:
                    error = f"Insufficient cash (${student_cash:.2f} available, ${actual_cost:.2f} needed)"
                elif action == "Sell":
                    if trade_ticker not in student_holdings:
                        error = "Asset not owned."
                    else:
                        owned_shares = student_holdings[trade_ticker]['shares']
                        if order_mode == "By Shares" and shares_to_trade > owned_shares + 0.0001:
                            error = f"Only {owned_shares:.4f} shares owned."
                        elif order_mode == "By Amount ($)":
                            current_position_value = owned_shares * live_price
                            if actual_cost > current_position_value + 0.01:
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
        st.markdown('<div class="card"><h3>📊 Market Movers</h3>', unsafe_allow_html=True)
        with st.spinner("Loading market data..."):
            stock_movers = get_top_movers(STOCK_TICKERS)
            etf_movers = get_top_movers(ETF_TICKERS)

        def _show_movers(items, label):
            gainers = [x for x in items if x[3] > 0][:5]
            losers = [x for x in items if x[3] < 0][-5:][::-1]
            if not gainers and not losers:
                st.caption("No data available.")
                return
            if gainers:
                st.markdown(f"**{label} ↑**")
                for ticker, name, price, chg in gainers:
                    st.markdown(f"**{ticker}** {name} — ${price:.2f} <span style='color:#10b981'>{chg:+.2f}%</span>", unsafe_allow_html=True)
            if losers:
                st.markdown(f"**{label} ↓**")
                for ticker, name, price, chg in losers:
                    st.markdown(f"**{ticker}** {name} — ${price:.2f} <span style='color:#f43f5e'>{chg:+.2f}%</span>", unsafe_allow_html=True)

        _show_movers(stock_movers, "Stock Gainers")
        st.markdown("<hr style='margin:0.5rem 0'>", unsafe_allow_html=True)
        _show_movers(etf_movers, "ETF Gainers")
        st.markdown('</div>', unsafe_allow_html=True)

with main_tab3:
    rcol1, rcol2 = st.columns([1, 2])
    
    with rcol1:
        st.markdown('<div class="card"><h3>Volatility Calculator</h3>', unsafe_allow_html=True)
        vol_ticker = stock_picker("vol")
        vol_period = st.selectbox("Period", ["10d", "1mo", "3mo", "6mo", "1y"], key="vol_period", label_visibility="collapsed")
        if vol_ticker:
            try:
                import yfinance as yf
                from utils.market import _flatten_cols
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
                st.markdown(f'<div style="font-size:2rem;font-weight:700;margin-bottom:0.5rem">${live_pr:.2f} <span style="font-size:0.9rem;font-weight:400;color:var(--text-muted)">{comp}</span></div>', unsafe_allow_html=True)
            c1, c2 = st.columns([3, 1])
            with c1:
                research_chart_period = st.selectbox("Period", options=list(CHART_PERIODS.keys()), format_func=lambda k: CHART_PERIODS[k], key="research_chart_period", label_visibility="collapsed", index=3)
            with c2:
                chart_style = st.selectbox("Style", ["Line", "Candlestick"], key="chart_style", label_visibility="collapsed")
            hist2 = fetch_full_history(vol_ticker, period=research_chart_period)
            if hist2 is not None and len(hist2) > 5:
                if chart_style == "Candlestick":
                    fig2 = plot_candlestick(vol_ticker, hist2, period_label=CHART_PERIODS[research_chart_period])
                else:
                    fig2 = go.Figure()
                    fig2.add_trace(go.Scatter(x=hist2.index, y=hist2['Close'], mode='lines', name=vol_ticker, line=dict(color='#3b82f6', width=2)))
                    fig2.update_layout(title=f"{vol_ticker} — {CHART_PERIODS[research_chart_period]}", yaxis_title="Price ($)", template="plotly_white", hovermode="x unified", margin=dict(l=0, r=0, t=30, b=50), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                    fig2.update_xaxes(title="Date", tickformat="%b %d", nticks=6, gridcolor='rgba(128,128,128,0.1)')
                    fig2.update_yaxes(side="right", gridcolor='rgba(128,128,128,0.1)')
                fig2.update_layout(height=380, margin=dict(l=0, r=0, t=35, b=50))
                st.plotly_chart(fig2, use_container_width=True, key="research_chart")
                if chart_style == "Candlestick":
                    st.caption("🟢 Green bar = price closed higher &nbsp;&nbsp;&nbsp; 🔴 Red bar = price closed lower")
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
        st.markdown("<hr style='margin:0.75rem 0; border:none; border-top:1px solid var(--border-color);'>", unsafe_allow_html=True)
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

with main_tab5:
    st.markdown('<div class="card"><h3>🏆 Classroom Standings</h3>', unsafe_allow_html=True)
    with st.spinner("Loading leaderboard..."):
        all_portfolios = get_gcs_database()
    
    if all_portfolios:
        records = []
        for email, profile in all_portfolios.items():
            # Exclude teacher from the general student leaderboard
            if email == "rpiana@stjohnsguam.com":
                continue
            name = profile.get("name", "Student")
            cash = profile.get("cash", 1000.0)
            holdings = profile.get("holdings", {})
            
            mv = 0.0
            for t, pos in holdings.items():
                p, _, _ = fetch_stock_market_data(t)
                if p is not None:
                    mv += pos["shares"] * p
            
            nw = cash + mv
            pl = nw - 1000.0
            pr = (pl / 1000.0) * 100
            
            records.append({
                "Rank": 0, "Student": name, "Net Worth": nw, "Return (%)": pr
            })
            
        if records:
            df = pd.DataFrame(records)
            df = df.sort_values("Net Worth", ascending=False).reset_index(drop=True)
            df["Rank"] = df.index + 1
            df["Net Worth"] = df["Net Worth"].map("${:,.2f}".format)
            df["Return (%)"] = df["Return (%)"].map("{:+.2f}%".format)
            
            def highlight_top(s):
                return ['background-color: rgba(16, 185, 129, 0.1); font-weight: bold' if s.name < 3 else '' for v in s]
            
            st.dataframe(df.style.apply(highlight_top, axis=1), use_container_width=True, hide_index=True)
        else:
            st.info("No participants found yet.")
    else:
        st.info("Could not load standings.")
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# 5. TEACHER ADMIN
# ==========================================
config_teacher_email = "rpiana@stjohnsguam.com"
if student_email == config_teacher_email:
    st.write("---")
    st.markdown('<div class="card"><h3>👨‍🏫 Teacher Administration</h3></div>', unsafe_allow_html=True)

    admin_tab1, admin_tab2 = st.tabs(["📊 Full Class Portfolio Data", "🧪 My Pilot Testing"])

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
                for t, pos in holdings.items():
                    p, _, _ = fetch_stock_market_data(t)
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
