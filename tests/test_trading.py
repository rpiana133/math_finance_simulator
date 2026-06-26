from unittest.mock import patch

from main import _validate_trade_inputs

ALL_TICKERS = {"AAPL", "SPY", "GOOGL"}
BASE_PROFILE: dict = {
    "cash": 100000,
    "holdings": {
        "AAPL": {"shares": 10.0, "total_cost": 150000},
    },
    "history": [],
}


def test_validate_buy_ok():
    valid, err, data = _validate_trade_inputs("AAPL", 150.0, "Buy", "Shares", 2.0, 0, BASE_PROFILE, ALL_TICKERS)
    assert valid is True
    assert err == ""
    assert data is not None
    assert data["action"] == "Buy"
    assert data["ticker"] == "AAPL"
    assert data["shares"] == 2.0


def test_validate_buy_insufficient_cash():
    valid, err, data = _validate_trade_inputs("AAPL", 150.0, "Buy", "Amount ($)", 0, BASE_PROFILE["cash"] // 100 + 1, BASE_PROFILE, ALL_TICKERS)
    assert valid is False
    assert "Insufficient cash" in err
    assert data is None


def test_validate_sell_not_owned():
    valid, err, data = _validate_trade_inputs("SPY", 400.0, "Sell", "Shares", 1.0, 0, BASE_PROFILE, ALL_TICKERS)
    assert valid is False
    assert err == "Not owned."
    assert data is None


def test_validate_sell_exceeds_shares():
    valid, err, data = _validate_trade_inputs("AAPL", 150.0, "Sell", "Shares", 15.0, 0, BASE_PROFILE, ALL_TICKERS)
    assert valid is False
    assert "Only" in err and "shares owned" in err
    assert data is None


def test_validate_sell_exceeds_amount():
    valid, err, data = _validate_trade_inputs("AAPL", 150.0, "Sell", "Amount ($)", 0, 2000.0, BASE_PROFILE, ALL_TICKERS)
    assert valid is False
    assert "Exceeds position value" in err
    assert data is None


def test_validate_invalid_ticker():
    valid, err, data = _validate_trade_inputs("INVALID", 100.0, "Buy", "Shares", 1.0, 0, BASE_PROFILE, ALL_TICKERS)
    assert valid is False
    assert "Invalid ticker" in err
    assert data is None


def test_validate_no_ticker():
    valid, err, data = _validate_trade_inputs("", 100.0, "Buy", "Shares", 1.0, 0, BASE_PROFILE, ALL_TICKERS)
    assert valid is False
    assert err == "Select a ticker"
    assert data is None


def test_validate_price_none():
    valid, err, data = _validate_trade_inputs("AAPL", None, "Buy", "Shares", 1.0, 0, BASE_PROFILE, ALL_TICKERS)
    assert valid is False
    assert "Price unavailable" in err
    assert data is None


def test_validate_buy_amount_mode():
    valid, err, data = _validate_trade_inputs("SPY", 400.0, "Buy", "Amount ($)", 0, 500.0, BASE_PROFILE, ALL_TICKERS)
    assert valid is True
    assert data["action"] == "Buy"
    assert data["shares"] == 500.0 / 400.0


@patch("main.fetch_stock_market_data", return_value=(150.0, None, None))
def test_execute_buy_new_holding(mock_fetch):
    from copy import deepcopy

    from main import _execute_trade

    profile = deepcopy(BASE_PROFILE)
    locks = {}
    saved = []

    def fake_save(email, p):
        saved.append((email, p))

    data = {"ticker": "SPY", "action": "Buy", "shares": 5.0, "cost": 750.0, "price": 150.0}
    success, error, event, details = _execute_trade(data, profile, "test@example.com", locks, fake_save, ALL_TICKERS)

    assert success is True
    assert event == "Buy"
    # new holding created
    assert profile["holdings"]["SPY"]["shares"] == 5.0
    assert profile["holdings"]["SPY"]["total_cost"] == 75000  # 750 * 100
    assert len(saved) == 1
    assert saved[0][0] == "test@example.com"


@patch("main.fetch_stock_market_data", return_value=(150.0, None, None))
def test_execute_buy_existing_holding(mock_fetch):
    from copy import deepcopy

    from main import _execute_trade

    profile = deepcopy(BASE_PROFILE)
    locks = {}
    saved = []

    def fake_save(email, p):
        saved.append((email, p))

    data = {"ticker": "AAPL", "action": "Buy", "shares": 3.0, "cost": 450.0, "price": 150.0}
    success, error, event, details = _execute_trade(data, profile, "test@example.com", locks, fake_save, ALL_TICKERS)

    assert success is True
    assert profile["holdings"]["AAPL"]["shares"] == 13.0
    assert profile["holdings"]["AAPL"]["total_cost"] == 150000 + 45000
    assert profile["cash"] == 100000 - 45000


@patch("main.fetch_stock_market_data", return_value=(150.0, None, None))
def test_execute_sell(mock_fetch):
    from copy import deepcopy

    from main import _execute_trade

    profile = deepcopy(BASE_PROFILE)
    locks = {}
    saved = []

    def fake_save(email, p):
        saved.append((email, p))

    data = {"ticker": "AAPL", "action": "Sell", "shares": 4.0, "cost": 600.0, "price": 150.0}
    success, error, event, details = _execute_trade(data, profile, "test@example.com", locks, fake_save, ALL_TICKERS)

    assert success is True
    assert event == "Sell"
    # Check unsettled cash
    assert profile["unsettled_cash"] > 0
    # Check holding reduced
    assert profile["holdings"]["AAPL"]["shares"] == 6.0
    # Check history
    assert len(profile["history"]) == 1
    assert profile["history"][0]["type"] == "Sell"


@patch("main.fetch_stock_market_data", return_value=(150.0, None, None))
def test_execute_sell_removes_holding(mock_fetch):
    from copy import deepcopy

    from main import _execute_trade

    profile = deepcopy(BASE_PROFILE)
    locks = {}
    saved = []

    def fake_save(email, p):
        saved.append((email, p))

    data = {"ticker": "AAPL", "action": "Sell", "shares": 10.0, "cost": 1500.0, "price": 150.0}
    success, error, event, details = _execute_trade(data, profile, "test@example.com", locks, fake_save, ALL_TICKERS)

    assert success is True
    assert "AAPL" not in profile["holdings"]


@patch("main.fetch_stock_market_data", return_value=(150.0, None, None))
def test_execute_insufficient_shares(mock_fetch):
    from copy import deepcopy

    from main import _execute_trade

    profile = deepcopy(BASE_PROFILE)
    locks = {}

    data = {"ticker": "AAPL", "action": "Sell", "shares": 99.0, "cost": 14850.0, "price": 150.0}
    success, error, event, details = _execute_trade(data, profile, "test@example.com", locks, lambda e, p: None, ALL_TICKERS)

    assert success is False
    assert "Insufficient shares" in error


@patch("main.fetch_stock_market_data", return_value=(150.0, None, None))
def test_execute_insufficient_cash(mock_fetch):
    from copy import deepcopy

    from main import _execute_trade

    profile = deepcopy(BASE_PROFILE)
    locks = {}

    data = {"ticker": "SPY", "action": "Buy", "shares": 9999.0, "cost": 1499850.0, "price": 150.0}
    success, error, event, details = _execute_trade(data, profile, "test@example.com", locks, lambda e, p: None, ALL_TICKERS)

    assert success is False
    assert "Insufficient cash" in error


def test_execute_invalid_ticker():
    from main import _execute_trade

    profile = {"cash": 100000, "holdings": {}, "history": []}
    data = {"ticker": "INVALID", "action": "Buy", "shares": 1.0, "cost": 100.0, "price": 100.0}
    success, error, event, details = _execute_trade(data, profile, "test@example.com", {}, lambda e, p: None, ALL_TICKERS)
    assert success is False
    assert "Invalid ticker" in error


def test_execute_negative_cash_raises():

    from main import _execute_trade

    profile = {"cash": 0, "holdings": {"AAPL": {"shares": 10.0, "total_cost": 150000}}, "history": []}
    data = {"ticker": "AAPL", "action": "Sell", "shares": 5.0, "cost": 750.0, "price": 150.0}
    with patch("main.fetch_stock_market_data", return_value=(150.0, None, None)):
        success, error, event, details = _execute_trade(data, profile, "test@example.com", {}, lambda e, p: None, ALL_TICKERS)
        # Sell doesn't affect cash (goes to unsettled), so cash stays 0 -> no error
        assert success is True
        assert profile["cash"] == 0
        assert profile["unsettled_cash"] > 0
