from unittest.mock import patch

from datetime import datetime

from services.sheets import (
    HEADERS,
    LEGACY_HEADERS,
    _is_legacy,
    save_weekly_snapshot,
)

_DT = datetime(2026, 9, 4, 12, 0, 0)


# ── Fake of the Google Sheets API method chain used in services/sheets.py ──
# Chain used: service.spreadsheets() returns API; API.values() returns Values
# with get()/update()/clear(); API.batchUpdate() takes body. Each returns an
# object whose .execute() returns a value.

class ExpectedResult:
    _payload = {"values": []}


class Call:
    """Execute wrapper that runs against a shared FakeService.""" 

    def __init__(self, service, fn):
        self.service = service
        self.fn = fn

    def execute(self):
        return self.fn(self.service)


class FakeValues:
    def __init__(self, service):
        self.service = service

    def get(self, **kw):
        return Call(self.service, lambda s: {"values": s.read(kw["range"])})

    def update(self, **kw):
        return Call(self.service, lambda s: s.write(kw["range"], kw["body"]["values"]))

    def clear(self, **kw):
        return Call(self.service, lambda s: s.clear(kw["range"]))


class FakeSheetsAPI:
    def __init__(self, service):
        self.service = service

    def values(self):
        return FakeValues(self.service)

    def batchUpdate(self, **kw):
        def _apply(s):
            s.batches.append(kw["body"]["requests"])
            for req in kw["body"]["requests"]:
                if "deleteDimension" in req:
                    rng = req["deleteDimension"]["range"]
                    start, end = rng["startIndex"], rng["endIndex"]
                    del s.grid[start:end]
            return {}
        return Call(self.service, _apply)


class FakeAPI:
    def __init__(self, service):
        self.service = service

    def spreadsheets(self):
        return FakeSheetsAPI(self.service)

    def values(self):
        return FakeValues(self.service)

    def batchUpdate(self, **kw):
        def _apply(s):
            s.batches.append(kw["body"]["requests"])
            return {}
        return Call(self.service, _apply)


class FakeService:
    """In-memory grid + batch log."""

    def __init__(self, starting_rows):
        self.grid = [list(r) for r in starting_rows if r]
        self.batches = []

    def read(self, rng):
        return [row[:] for row in self.grid]

    def write(self, rng, values):
        start_row = int(rng[1:].split(":")[0]) - 1
        for offset, row in enumerate(values):
            idx = start_row + offset
            while len(self.grid) <= idx:
                self.grid.append([])
            self.grid[idx] = list(row)
        return {}

    def clear(self, rng):
        if rng == "A1:Z1":
            self.grid = [self.grid[0]] if self.grid else [HEADERS[:]]
        return {}


def _build_rows(live):
    """Mirror the rows save_weekly_snapshot produces, for assertions."""
    rows = []
    for item in live:
        shares = item["Shares"]
        avg = float(str(item["Avg Price"]).lstrip("$"))
        lp = float(str(item["Live Price"]).lstrip("$"))
        rows.append(["2026-W36", "2026-09-04", item["Ticker"], shares,
                     avg, lp, round(shares * lp, 2), item["Return"], 5000.0])
    return rows


PORTFOLIO = {
    "total": 5000.0,
    "live_data": [
        {"Ticker": "AAPL", "Shares": 10, "Avg Price": "$180.00",
         "Live Price": "$185.00", "Value": "$1850.00", "Return": 2.78},
        {"Ticker": "MSFT", "Shares": 5, "Avg Price": "$300.00",
         "Live Price": "$320.00", "Value": "$1600.00", "Return": 6.67},
    ],
}


def test_is_legacy_true():
    assert _is_legacy(list(LEGACY_HEADERS)) is True


def test_is_legacy_false_for_new():
    assert _is_legacy(list(HEADERS)) is False


def test_is_legacy_empty():
    assert _is_legacy([]) is False


@patch("services.sheets._build_sheets")
def test_append_new_week_rows(mock_build):
    service = FakeService([HEADERS[:]])
    fake = FakeAPI(service)
    mock_build.return_value = fake

    creds = {"token": "t"}
    info, url = save_weekly_snapshot(creds, PORTFOLIO, "spread1", now=_DT)

    assert info["action"] == "appended"
    assert info["week"] == "2026-W36"
    expected = _build_rows(PORTFOLIO["live_data"])
    assert service.grid[1] == expected[0]
    assert service.grid[2] == expected[1]
    assert len(service.grid) == 3


@patch("services.sheets._build_sheets")
def test_update_existing_week_rewrites(mock_build):
    # pre-existing row for the same week
    service = FakeService([HEADERS[:], ["2026-W36", "2026-09-01", "AAPL",
                                        10, 180.0, 180.0, 1800.0, 0.0, 4900.0]])
    fake = FakeAPI(service)
    mock_build.return_value = fake

    info, url = save_weekly_snapshot({"token": "t"}, PORTFOLIO, "spread1", now=_DT)

    assert info["action"] == "updated"
    # old week rows deleted then appended fresh
    assert service.grid[1] == _build_rows(PORTFOLIO["live_data"])[0]
    assert service.grid[2] == _build_rows(PORTFOLIO["live_data"])[1]


@patch("services.sheets._build_sheets")
def test_no_holdings_single_row(mock_build):
    service = FakeService([HEADERS[:]])
    fake = FakeAPI(service)
    mock_build.return_value = fake

    p = {"total": 5000.0, "live_data": []}
    info, url = save_weekly_snapshot({"token": "t"}, p, "spread1", now=_DT)

    assert len(service.grid) == 2
    assert service.grid[1][0] == "2026-W36"
    assert service.grid[1][-1] == 5000.0
