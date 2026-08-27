from __future__ import annotations

import html
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock

from utils.helpers import STARTING_CASH_CENTS, _cents
from utils.market import fetch_stock_market_data, get_dividends
from utils.storage import load_student_profile, save_student_profile

_profiles: dict = {}
_profile_locks: dict[str, Lock] = {}
_shared_executor = ThreadPoolExecutor(max_workers=8)


def _migrate_profile(p: dict | None) -> dict | None:
    if p is None or isinstance(p.get("cash"), int):
        return p
    dep = p.get("total_deposits", 0)
    cash_in_cents = isinstance(dep, int)
    p["cash"] = (
        int(round(p.get("cash", 0)))
        if cash_in_cents
        else int(round(p.get("cash", 0) * 100))
    )
    p["unsettled_cash"] = int(
        round(p.get("unsettled_cash", 0) * (1 if cash_in_cents else 100))
    )
    p["total_dividends_earned"] = int(
        round(p.get("total_dividends_earned", 0) * (1 if cash_in_cents else 100))
    )
    p["total_deposits"] = dep if isinstance(dep, int) else int(round(dep * 100))
    for h in p.get("holdings", {}).values():
        h["total_cost"] = int(round(h.get("total_cost", 0) * 100))
    for e in p.get("unsettled_entries", []):
        e["amount"] = int(round(e.get("amount", 0) * 100))
    return p


def _clean_dust_holdings(p: dict) -> None:
    for t in [t for t, h in p.get("holdings", {}).items() if h.get("total_cost", 0) <= 0 or h.get("shares", 0) <= 1e-6]:
        del p["holdings"][t]


def _get(email: str) -> dict | None:
    if email not in _profiles:
        _profiles[email] = _migrate_profile(load_student_profile(email))
        _p = _profiles[email]
        if _p is not None:
            _clean_dust_holdings(_p)
    else:
        # If the cached profile is a fresh empty one, attempt to reload/migrate it
        profile = _profiles[email]
        if profile is not None:
            is_fresh_empty = (
                len(profile.get("holdings", {})) == 0 and
                len(profile.get("history", [])) == 0 and
                profile.get("cash") == 100000
            )
            if is_fresh_empty:
                loaded = load_student_profile(email)
                if loaded is not None:
                    _profiles[email] = _migrate_profile(loaded)
                    _clean_dust_holdings(_profiles[email])
    return _profiles[email]


def _save(email: str, profile: dict) -> None:
    _profiles[email] = profile
    save_student_profile(email, profile)


def _portfolio(profile: dict) -> dict:
    cash = profile.get("cash", STARTING_CASH_CENTS) / 100.0
    unsettled = profile.get("unsettled_cash", 0) / 100.0
    holdings = profile.get("holdings", {})
    history = profile.get("history", [])
    total_hold = total_cost = 0.0
    live = []
    hold_items = list(holdings.items())
    if hold_items:
        futs = {
            _shared_executor.submit(fetch_stock_market_data, t): t
            for t, _ in hold_items
        }
        prices: dict[str, float] = {}
        try:
            for fut in as_completed(futs, timeout=15):
                try:
                    price = fut.result()[0]
                except Exception:
                    continue
                if price is not None and not math.isnan(price):
                    prices[futs[fut]] = price
        except Exception:
            pass
        for ticker, pos in hold_items:
            shares = pos.get("shares", 0)
            tc = pos.get("total_cost", 0) / 100.0
            if shares <= 0 or tc <= 0:
                continue
            price = prices.get(ticker)
            if price is None:
                continue
            cv = shares * price
            total_hold += cv
            total_cost += tc
            avg = tc / shares
            ret = ((price - avg) / avg) * 100
            live.append(
                {
                    "Ticker": ticker,
                    "Shares": round(pos["shares"], 4),
                    "Avg Price": f"${avg:.2f}",
                    "Live Price": f"${price:.2f}",
                    "Value": f"${cv:.2f}",
                    "Return": ret,
                }
            )
    total = cash + unsettled + total_hold
    cap = (STARTING_CASH_CENTS + profile.get("total_deposits", 0)) / 100.0
    pl = total_hold - total_cost
    pl_pct = (pl / total_cost) * 100 if total_cost else 0.0
    prices = {item["Ticker"]: float(item["Live Price"].lstrip("$")) for item in live}
    return {
        "cash": cash,
        "unsettled": unsettled,
        "holdings": holdings,
        "total_hold": total_hold,
        "total_cost": total_cost,
        "total": total,
        "capital": cap,
        "pl": pl,
        "pl_pct": pl_pct,
        "live_data": live,
        "prices": prices,
        "history": history,
    }


def _process_dividends(email: str, profile: dict) -> dict:
    lock = _profile_locks.setdefault(email, Lock())
    with lock:
        tracker = profile.setdefault("dividend_tracker", {})
        now = datetime.now()
        total_c = 0
        for ticker, pos in list(profile.get("holdings", {}).items()):
            last = tracker.get(ticker)
            divs = get_dividends(ticker)
            if divs is None or divs.empty:
                continue
            d = divs.index[-1]
            amt = float(divs.iloc[-1])
            if last is None:
                tracker[ticker] = d.isoformat()
                continue
            if d > datetime.fromisoformat(last):
                a_c = _cents(pos["shares"] * amt)
                if a_c > 0:
                    profile["cash"] += a_c
                    profile["total_dividends_earned"] = (
                        profile.get("total_dividends_earned", 0) + a_c
                    )
                    profile.setdefault("history", []).append(
                        {
                            "type": "dividend",
                            "ticker": ticker,
                            "shares": round(pos["shares"], 4),
                            "dividend_per_share": round(amt, 4),
                            "total": round(pos["shares"] * amt, 2),
                            "time": now.isoformat(),
                        }
                    )
                    total_c += a_c
                tracker[ticker] = d.isoformat()
        if total_c > 0:
            _save(email, profile)
    return profile


def _process_weekly(email: str, profile: dict) -> tuple[int | None, int]:
    lock = _profile_locks.setdefault(email, Lock())
    with lock:
        now = datetime.now()
        last = profile.get("last_weekly_deposit")
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


def _process_settlement(email: str, profile: dict) -> dict:
    lock = _profile_locks.setdefault(email, Lock())
    with lock:
        now = datetime.now()
        entries = profile.get("unsettled_entries", [])
        settled_c = 0
        remaining = []
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


def _check_alerts(profile: dict) -> list[str]:
    alerts = profile.get("alerts", [])
    triggered = []
    for a in alerts:
        price, _, _ = fetch_stock_market_data(a["ticker"])
        if price is None:
            continue
        if a["direction"] == "above" and price >= a["price"]:
            triggered.append(
                f"{html.escape(a['ticker'])} hit ${price:.2f} (above ${a['price']:.2f})"
            )
        elif a["direction"] == "below" and price <= a["price"]:
            triggered.append(
                f"{html.escape(a['ticker'])} dropped to ${price:.2f} (below ${a['price']:.2f})"
            )
    return triggered
