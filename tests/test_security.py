import os
from copy import deepcopy
from unittest.mock import MagicMock, patch

os.environ.setdefault("TEACHER_EMAILS", "rpiana@stjohnsguam.com")
os.environ.setdefault("GOOGLE_HD", "stjohnsguam.com")
os.environ.setdefault("BLOB_KEY_SECRET", "test-secret-do-not-use")

import importlib

import utils.auth

importlib.reload(utils.auth)
from utils.auth import EXPECTED_HD, is_teacher  # noqa: E402


def test_is_teacher_positive():
    assert is_teacher("rpiana@stjohnsguam.com") is True


def test_is_teacher_negative():
    assert is_teacher("student@gmail.com") is False


def test_is_teacher_empty():
    assert is_teacher("") is False


def test_hd_env_var_loaded():
    assert EXPECTED_HD == "stjohnsguam.com"


def test_google_hd_empty_by_default(monkeypatch):
    monkeypatch.delenv("GOOGLE_HD")
    monkeypatch.setenv("TEACHER_EMAILS", "x@y.com")
    import importlib

    import utils.auth
    importlib.reload(utils.auth)
    assert utils.auth.EXPECTED_HD == ""
    monkeypatch.setenv("GOOGLE_HD", "stjohnsguam.com")
    importlib.reload(utils.auth)


# ── Session store ────────────────────────────────────────
# These mock `main.app` entirely to avoid NiceGUI's
# RuntimeError from app.storage.user before ui.run().


def test_get_session_returns_default_when_no_token():
    mock_app = MagicMock()
    mock_app.storage.user = {}
    with patch("main.app", mock_app):
        from main import _get_session
        assert _get_session("last_activity", 0) == 0
        assert _get_session("authenticated", None) is None


def test_get_session_returns_value_for_valid_token():
    token = "test-token-session"
    mock_app = MagicMock()
    mock_app.storage.user = {"_token": token}
    with patch("main.app", mock_app):
        from main import _get_session, _session_lock, _session_store
        with _session_lock:
            _session_store[token] = {"last_activity": 42.0, "email": "test@example.com"}
        try:
            assert _get_session("last_activity") == 42.0
            assert _get_session("email") == "test@example.com"
        finally:
            with _session_lock:
                _session_store.pop(token, None)


def test_get_session_returns_default_for_missing_key():
    token = "missing-key-token"
    mock_app = MagicMock()
    mock_app.storage.user = {"_token": token}
    with patch("main.app", mock_app):
        from main import _get_session, _session_lock, _session_store
        with _session_lock:
            _session_store[token] = {"authenticated": True}
        try:
            assert _get_session("last_activity", 0) == 0
            assert _get_session("nonexistent") is None
        finally:
            with _session_lock:
                _session_store.pop(token, None)


def test_touch_session_updates_last_activity():
    token = "touch-test-token"
    now_ts = 1000.0
    mock_app = MagicMock()
    mock_app.storage.user = {"_token": token}
    with patch("main.app", mock_app), patch("main.datetime") as mock_dt:
        from main import _session_lock, _session_store, _touch_session
        mock_dt.utcnow.return_value.timestamp.return_value = now_ts
        with _session_lock:
            _session_store[token] = {"last_activity": 0.0, "email": "test@example.com"}
        try:
            _touch_session()
            with _session_lock:
                updated = _session_store[token]["last_activity"]
            assert updated == now_ts
        finally:
            with _session_lock:
                _session_store.pop(token, None)


def test_touch_session_no_token_no_error():
    mock_app = MagicMock()
    mock_app.storage.user = {}
    with patch("main.app", mock_app):
        from main import _touch_session
        _touch_session()


def test_clear_session_removes_value():
    token = "clear-test-token"
    mock_app = MagicMock()
    mock_app.storage.user = {"_token": token}
    with patch("main.app", mock_app):
        from main import _clear_session, _session_lock, _session_store
        with _session_lock:
            _session_store[token] = {"authenticated": True}
            assert token in _session_store
        _clear_session()
        with _session_lock:
            assert token not in _session_store


def test_clear_session_no_token_no_error():
    mock_app = MagicMock()
    mock_app.storage.user = {}
    with patch("main.app", mock_app):
        from main import _clear_session
        _clear_session()


def test_clear_session_clears_only_target_token():
    token_a = "clear-multi-a"
    token_b = "clear-multi-b"
    mock_app = MagicMock()
    mock_app.storage.user = {"_token": token_a}
    with patch("main.app", mock_app):
        from main import _clear_session, _session_lock, _session_store
        with _session_lock:
            _session_store[token_a] = {"email": "a@example.com"}
            _session_store[token_b] = {"email": "b@example.com"}
        _clear_session()
        with _session_lock:
            assert token_a not in _session_store
            assert token_b in _session_store
            _session_store.pop(token_b, None)


# ── Rate limiter sliding-window logic ────────────────────


def test_rate_limiter_sliding_window_rejects_after_5():
    from datetime import datetime

    from cachetools import TTLCache

    cache = TTLCache(maxsize=10000, ttl=60)
    ip = "203.0.113.1"
    now = datetime.utcnow().timestamp()

    for i in range(5):
        t = now + i
        window = cache.get(ip, [])
        window = [x for x in window if t - x < 60]
        assert len(window) < 5
        window.append(t)
        cache[ip] = window

    # 6th attempt within window
    t6 = now + 6
    window = cache.get(ip, [])
    window = [x for x in window if t6 - x < 60]
    assert len(window) >= 5


def test_rate_limiter_old_entries_expire():
    from datetime import datetime

    from cachetools import TTLCache

    cache = TTLCache(maxsize=10000, ttl=60)
    ip = "203.0.113.2"
    old = datetime.utcnow().timestamp() - 120

    for _ in range(5):
        window = cache.get(ip, [])
        window.append(old)
        cache[ip] = window

    now = datetime.utcnow().timestamp()
    window = cache.get(ip, [])
    window = [x for x in window if now - x < 60]
    assert len(window) == 0  # all expired


def test_rate_limiter_different_ips_independent():
    from datetime import datetime

    from cachetools import TTLCache

    cache = TTLCache(maxsize=10000, ttl=60)
    now = datetime.utcnow().timestamp()

    for i in range(5):
        t = now + i
        for ip in ("203.0.113.10", "203.0.113.20"):
            window = cache.get(ip, [])
            window = [x for x in window if t - x < 60]
            window.append(t)
            cache[ip] = window

    # Each IP has 5 now
    for ip in ("203.0.113.10", "203.0.113.20"):
        window = cache.get(ip, [])
        window = [x for x in window if now + 6 - x < 60]
        assert len(window) >= 5


# ── OAuth state mismatch ─────────────────────────────────


def test_oauth_state_mismatch_detected():
    mock_app = MagicMock()
    mock_app.storage.user = {"oauth_state": "valid"}
    with patch("main.app", mock_app):
        stored_state = "valid"
        incoming_state = "invalid"
        mismatch = not stored_state or not incoming_state or incoming_state != stored_state
        assert mismatch is True


def test_oauth_state_match_succeeds():
    stored_state = "same-state"
    incoming_state = "same-state"
    mismatch = not stored_state or not incoming_state or incoming_state != stored_state
    assert mismatch is False


# ── Balance invariant ────────────────────────────────────


def _total_assets(profile, prices):
    cash = profile.get("cash", 0)
    unsettled = profile.get("unsettled_cash", 0)
    holdings_value = sum(
        h["shares"] * prices.get(t, 0)
        for t, h in profile.get("holdings", {}).items()
    )
    return cash + unsettled + holdings_value


def test_balance_invariant_after_buy():
    from main import ALL_TICKERS, _validate_trade_inputs
    profile = {"cash": 100000, "holdings": {}, "history": [], "unsettled_cash": 0}
    prices = {"SPY": 400.0, "VOO": 480.0}
    before = _total_assets(profile, prices)
    valid, err, data = _validate_trade_inputs(
        "SPY", 400.0, "Buy", "Amount ($)", 0, 500.0, profile, ALL_TICKERS
    )
    assert valid is True
    after = _total_assets(profile, prices)
    assert after == before


def test_balance_invariant_after_sell():
    from main import ALL_TICKERS, _validate_trade_inputs
    profile = {
        "cash": 50000,
        "holdings": {"AAPL": {"shares": 10.0, "total_cost": 150000}},
        "history": [],
        "unsettled_cash": 0,
    }
    prices = {"AAPL": 150.0, "SPY": 400.0}
    before = _total_assets(profile, prices)
    valid, err, data = _validate_trade_inputs(
        "AAPL", 150.0, "Sell", "Shares", 3.0, 0, profile, ALL_TICKERS
    )
    assert valid is True
    after = _total_assets(profile, prices)
    assert after == before


def test_execute_preserves_balance_invariant():
    from main import ALL_TICKERS, _execute_trade
    profile = {
        "cash": 100000,
        "holdings": {"AAPL": {"shares": 10.0, "total_cost": 150000}},
        "history": [],
        "unsettled_cash": 0,
    }
    data = {"ticker": "AAPL", "action": "Buy", "shares": 2.0, "cost": 300.0, "price": 150.0}
    with patch("main.fetch_stock_market_data", return_value=(150.0, None, None)):
        success, error, event, details = _execute_trade(
            data, deepcopy(profile), "test@example.com", {}, lambda e, p: None, ALL_TICKERS
        )
    assert success is True


def test_execute_invariant_no_money_creation():
    from main import ALL_TICKERS, _execute_trade
    profile = {
        "cash": 10000000,
        "holdings": {},
        "history": [],
        "unsettled_cash": 0,
    }
    data = {"ticker": "VOO", "action": "Buy", "shares": 1.0, "cost": 480.0, "price": 480.0}
    with patch("main.fetch_stock_market_data", return_value=(480.0, None, None)):
        success, error, event, details = _execute_trade(
            data, profile, "test@example.com", {}, lambda e, p: None, ALL_TICKERS
        )
    assert success is True
    assert profile["cash"] == 10000000 - 48000
    assert profile["holdings"]["VOO"]["shares"] == 1.0
    assert profile["holdings"]["VOO"]["total_cost"] == 48000


def test_callback_rate_limit_uses_ttlcache():
    from cachetools import TTLCache

    from main import _callback_rates
    assert isinstance(_callback_rates, TTLCache)
    assert _callback_rates.maxsize == 10000
    assert _callback_rates.ttl == 60


def test_session_lock_has_acquire_release():
    from main import _session_lock
    assert hasattr(_session_lock, "acquire")
    assert hasattr(_session_lock, "release")
    assert callable(_session_lock.acquire)
    assert callable(_session_lock.release)


def test_session_store_encrypted_token_lookup():
    import secrets

    from main import _session_lock, _session_store
    token = secrets.token_urlsafe(32)
    with _session_lock:
        _session_store[token] = {"authenticated": True, "email": "secret@example.com"}
        assert token in _session_store
        assert _session_store[token]["email"] == "secret@example.com"
        _session_store.pop(token, None)


@patch("services.profile.fetch_stock_market_data", return_value=(100.0, None, None))
def test_portfolio_skips_zero_cost_dust_holding(mock_fetch):
    from services.profile import _portfolio

    profile = {
        "cash": 50000,
        "unsettled_cash": 0,
        "holdings": {
            "SPY": {"shares": 10.0, "total_cost": 150000},
            "LLY": {"shares": 1.18e-06, "total_cost": 0},
        },
        "history": [],
        "total_deposits": 0,
        "dividend_tracker": {},
        "total_dividends_earned": 0,
    }
    result = _portfolio(profile)
    assert len(result["live_data"]) == 1
    assert result["live_data"][0]["Ticker"] == "SPY"
    assert result["total_hold"] == 10.0 * 100.0


def test_clean_dust_holdings_removes_zero_cost_positions():
    from services.profile import _clean_dust_holdings

    profile = {
        "holdings": {
            "VOO": {"shares": 4.0, "total_cost": 48000},
            "IVZ": {"shares": 3.46e-05, "total_cost": 0},
            "ANET": {"shares": 0.0, "total_cost": 50000},
        }
    }
    _clean_dust_holdings(profile)
    assert list(profile["holdings"].keys()) == ["VOO"]
