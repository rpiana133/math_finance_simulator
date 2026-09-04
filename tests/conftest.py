import pytest


@pytest.fixture(autouse=True)
def market_open(monkeypatch):
    """Default the market to OPEN so ordinary trade tests stay deterministic
    regardless of the day they run. Tests that exercise closed-market behavior
    override this by patching main._is_market_closed directly."""
    monkeypatch.setattr("main._is_market_closed", lambda *a, **k: False)
    yield
