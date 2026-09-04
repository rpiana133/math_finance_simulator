from unittest.mock import patch

from datetime import datetime

from main import _is_market_closed, _guam_date, _execute_trade, ALL_TICKERS


def _trade_data():
    return {
        "ticker": "SPY",
        "action": "Buy",
        "shares": 5.0,
        "cost": 750.0,
        "price": 150.0,
    }


BASE_PROFILE = {
    "cash": 100000,
    "holdings": {},
    "history": [],
}


# ── _guam_date / _is_market_closed date logic ─────────────────────────

def test_guam_date_shift():
    # 2026-09-04 15:00 UTC -> 2026-09-05 01:00 Guam (next day)
    utc = datetime(2026, 9, 4, 15, 0, 0)
    assert _guam_date(utc) == (2026, 9, 5)

    # 2026-09-04 12:00 UTC -> 2026-09-04 22:00 Guam (same day)
    utc = datetime(2026, 9, 4, 12, 0, 0)
    assert _guam_date(utc) == (2026, 9, 4)


def test_weekday_open():
    # Fri 2026-09-04, non-holiday
    utc = datetime(2026, 9, 4, 12, 0, 0)
    assert _is_market_closed(utc) is False


def test_saturday_closed():
    utc = datetime(2026, 9, 5, 0, 0, 0)  # Guam Sat 09/05
    assert _is_market_closed(utc) is True


def test_sunday_closed():
    utc = datetime(2026, 9, 6, 12, 0, 0)  # Guam Sun 09/06
    assert _is_market_closed(utc) is True


def test_labor_day_closed():
    # Guam Mon 2026-09-07 = Labor Day (US market holiday)
    utc = datetime(2026, 9, 7, 4, 0, 0)
    assert _guam_date(utc) == (2026, 9, 7)
    assert _is_market_closed(utc) is True


def test_regular_weekday_not_holiday_open():
    # Wed 2026-09-09 Guam is a normal open day (not a weekend or holiday).
    utc = datetime(2026, 9, 9, 2, 0, 0)  # +10h -> Guam Wed 09/09 12:00
    assert _guam_date(utc) == (2026, 9, 9)
    assert _is_market_closed(utc) is False


def test_christmas_closed():
    # Guam Fri 2026-12-25
    utc = datetime(2026, 12, 25, 3, 0, 0)
    assert _guam_date(utc) == (2026, 12, 25)
    assert _is_market_closed(utc) is True


# ── _execute_trade gating when market closed ─────────────────────────

def test_execute_trade_rejected_when_market_closed():
    with patch("main._is_market_closed", return_value=True):
        success, error, event, details = _execute_trade(
            _trade_data(), dict(BASE_PROFILE), "test@example.com",
            {}, lambda e, p: None, ALL_TICKERS,
        )
        assert success is False
        assert "Market closed" in error
        assert event is None
        assert details is None
