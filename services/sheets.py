from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.market import fetch_full_history

logger = logging.getLogger(__name__)

SHEET_TITLE = "My Stock Tracker"
WEEKLY_LOG_TAB = "Weekly Log"

# Row-per-holding, graph-friendly schema for the snapshot tab. One row per
# (week, holding); repeated Net Worth on every row so a whole-account
# value-over-time chart is easy too.
HEADERS = [
    "Week",
    "Date",
    "Ticker",
    "Shares",
    "Avg Price",
    "Live Price",
    "Value",
    "Return %",
    "Net Worth",
]
# Legacy blob schema that used to cram the whole portfolio into one Ticker cell.
LEGACY_HEADERS = [
    "Week",
    "Date",
    "Ticker",
    "Shares",
    "Avg Price",
    "Live Price",
    "Value",
    "Cash",
    "Net Worth",
]

# Week-to-week price history log: one row per (ticker, week) since buy.
WEEKLY_LOG_HEADERS = [
    "Week",
    "Date",
    "Ticker",
    "Close Price",
    "Avg Price",
    "Value",
    "Return %",
]

# Number formats per column index (0-based, applied to data rows).
_NUM_FMT = "0.00"
_HEADER_BG = {"red": 0.85, "green": 0.9, "blue": 0.95}
_BACKFILL_PERIOD = "1y"  # how far back to pull weekly closes when no buy date known


def _make_credentials(credentials_dict: dict[str, Any]) -> Credentials:
    return Credentials(
        token=credentials_dict.get("token"),
        refresh_token=credentials_dict.get("refresh_token"),
        token_uri=credentials_dict.get("token_uri"),
        client_id=credentials_dict.get("client_id"),
        client_secret=credentials_dict.get("client_secret"),
        scopes=credentials_dict.get("scopes"),
    )


def _build_sheets(credentials_dict: dict[str, Any]):
    """Build a Sheets API service using the student's own OAuth credentials."""
    return build("sheets", "v4", credentials=_make_credentials(credentials_dict))


def create_spreadsheet(credentials_dict: dict[str, Any]) -> str:
    """Create a fresh 'My Stock Tracker' spreadsheet in the student's Drive.

    Returns the new spreadsheetId.
    """
    sheets = _build_sheets(credentials_dict)
    body = {"properties": {"title": SHEET_TITLE}}
    created = (
        sheets.spreadsheets()
        .create(body=body, fields="spreadsheetId")
        .execute()
    )
    return created["spreadsheetId"]


def _read_sheet(service, spreadsheet_id: str, tab: str | None = None) -> list[list[str]]:
    rng = f"'{tab}'!A:Z" if tab else "A:Z"
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=rng)
        .execute()
    )
    return result.get("values", [])


def _is_legacy(header_row: list[str]) -> bool:
    """Detect the old blob schema by its distinctive headers."""
    if not header_row:
        return False
    return (header_row[:2] == ["Week", "Date"]
            and len(header_row) >= 3
            and header_row[2] == "Ticker"
            and "Cash" in header_row)


def _reset_to_new_schema(service, spreadsheet_id: str) -> None:
    """Wipe the sheet and write the new headers (used to migrate legacy sheets)."""
    rows = _read_sheet(service, spreadsheet_id)
    last_row = len(rows)
    if last_row >= 1:
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=f"A1:Z{max(last_row, 1)}"
        ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="A1",
        valueInputOption="USER_ENTERED",
        body={"values": [HEADERS]},
    ).execute()


def _ensure_headers(service, spreadsheet_id: str) -> None:
    """Write the new header row if blank or reset if the old schema is present."""
    rows = _read_sheet(service, spreadsheet_id)
    header = rows[0] if rows else []
    if not header or not header[0]:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="A1",
            valueInputOption="USER_ENTERED",
            body={"values": [HEADERS]},
        ).execute()
    elif _is_legacy(header):
        _reset_to_new_schema(service, spreadsheet_id)


def _weeks_map(rows: list[list[str]]) -> dict[str, list[int]]:
    """Map 'Week' key -> list of 1-based data row numbers for that week."""
    weeks: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        if i == 0:
            continue
        if row and row[0]:
            weeks.setdefault(row[0].strip(), []).append(i + 1)
    return weeks


def _delete_week_rows(service, spreadsheet_id: str, week_key: str,
                      rows: list[list[str]], sheet_id: int = 0) -> int:
    """Delete all rows belonging to an existing week; returns the count removed."""
    del_grid = []
    for i, row in enumerate(rows):
        if i == 0:
            continue
        if row and row[0].strip() == week_key:
            del_grid.append(i)  # 0-based grid index
    if not del_grid:
        return 0
    requests = [
        {"deleteDimension": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS",
                       "startIndex": g, "endIndex": g + 1},
        }}
        for g in reversed(del_grid)
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()
    return len(del_grid)


def _apply_formatting(service, spreadsheet_id: str, num_data_rows: int,
                      sheet_id: int = 0, headers: list[str] | None = None) -> None:
    """Bold + fill headers, freeze header row, size columns, format numbers."""
    headers = headers or HEADERS
    requests = []

    header_format = {
        "textFormat": {"bold": True},
        "backgroundColor": _HEADER_BG,
    }
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                       "startColumnIndex": 0, "endColumnIndex": len(headers)},
            "cell": {"userEnteredFormat": header_format},
            "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColor",
        }
    })

    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # Number formats on numeric data columns.
    if num_data_rows > 0:
        number_cols = [i for i, h in enumerate(headers) if h
                       not in ("Week", "Date", "Ticker")]
        for col in number_cols:
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1,
                               "endRowIndex": num_data_rows + 1,
                               "startColumnIndex": col, "endColumnIndex": col + 1},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": _NUM_FMT}}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            })

    requests.append({"autoResizeDimensions": {
        "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS",
                        "startIndex": 0, "endIndex": len(headers)}
    }})

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


def save_weekly_snapshot(
    credentials_dict: dict[str, Any],
    portfolio: dict,
    spreadsheet_id: str | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    """Write the current week's holdings as one row per holding.

    Rows use the graph-friendly schema (Week, Date, Ticker, Shares, Avg Price,
    Live Price, Value, Return %, Net Worth). If `spreadsheet_id` is provided it is
    reused; otherwise a new spreadsheet is created. Re-exporting the same ISO week
    rewrites that week's rows in place. Legacy blob-format sheets are reset.

    Returns (info, spreadsheetUrl).
    """
    now = now or datetime.now()
    week_key = f"{now.year}-W{now.isocalendar()[1]:02d}"
    date_str = now.strftime("%Y-%m-%d")

    net_worth = portfolio.get("total", 0.0)
    live = portfolio.get("live_data", [])

    if live:
        rows = []
        for item in live:
            def _num(s):
                return float(str(s).lstrip("$").replace(",", ""))
            ticker = item.get("Ticker", "")
            shares = item.get("Shares", 0)
            avg = _num(item.get("Avg Price", 0))
            live_price = _num(item.get("Live Price", 0))
            value = shares * live_price
            ret = item.get("Return", 0.0)
            rows.append([
                week_key, date_str, ticker, shares, avg, live_price,
                round(value, 2), round(ret, 2), round(net_worth, 2),
            ])
    else:
        # All cash / no holdings — keep a single row so the chart still has Net Worth.
        rows = [[week_key, date_str, "", "", "", "", "", "", round(net_worth, 2)]]

    try:
        service = _build_sheets(credentials_dict)
        spreadsheet_id = spreadsheet_id or create_spreadsheet(credentials_dict)
        _ensure_headers(service, spreadsheet_id)
        _apply_formatting(service, spreadsheet_id, 0)

        all_rows = _read_sheet(service, spreadsheet_id)
        weeks = _weeks_map(all_rows)

        if week_key in weeks:
            _delete_week_rows(service, spreadsheet_id, week_key, all_rows)
            action = "updated"
        else:
            action = "appended"

        # Recompute the insertion row after any deletion; append after last data row.
        all_rows = _read_sheet(service, spreadsheet_id)
        last_data = 1
        for i, row in enumerate(all_rows):
            if i == 0:
                continue
            if row and row[0]:
                last_data = i + 1
        start = last_data + 1

        end = start + len(rows) - 1
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"A{start}:I{end}",
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()

        _apply_formatting(service, spreadsheet_id, start + len(rows) - 1)

        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        return {
            "action": action,
            "week": week_key,
            "spreadsheet_id": spreadsheet_id,
        }, url
    except HttpError as e:
        logger.error(f"Sheets API error: {e}")
        raise


# ── Weekly Log (week-to-week price history) ───────────────────────────

def _iso_week(date: datetime) -> str:
    return f"{date.year}-W{date.isocalendar()[1]:02d}"


def _weekly_close_series(ticker: str, start: datetime) -> pd.Series:
    """Return a Series {week_key: friday_close} for `ticker` from `start` onward.

    Pulls daily OHLCV via fetch_full_history and resamples to weekly (Friday)
    closes. Returns an empty Series if no data is available.
    """
    empty = pd.Series(dtype=float)
    df = fetch_full_history(ticker, period=_BACKFILL_PERIOD)
    if df is None or df.empty or "Close" not in df:
        return empty
    closes = df["Close"].dropna()
    if closes.empty:
        return empty
    weekly = closes.resample("W-FRI").last()
    start_ts = pd.Timestamp(start)
    weekly = weekly[weekly.index >= start_ts.normalize()]
    if weekly.empty:
        return empty
    out = {}
    for ts, price in weekly.items():
        out[_iso_week(ts.to_pydatetime())] = float(price)
    series = pd.Series(out)
    series.index.name = "week"
    return series


def _buy_week_for_ticker(profile: dict, ticker: str) -> datetime | None:
    """Earliest week we have price data for: from the first Buy event if any."""
    entries = [
        e for e in profile.get("history", [])
        if isinstance(e, dict) and e.get("type") == "Buy" and e.get("ticker") == ticker
        and e.get("time")
    ]
    if not entries:
        return None
    times = []
    for e in entries:
        raw = e["time"]
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                times.append(datetime.strptime(raw, fmt))
                break
            except ValueError:
                continue
    return min(times) if times else None


def build_weekly_log_rows(
    portfolio: dict,
    profile: dict | None = None,
    now: datetime | None = None,
) -> list[list]:
    """Build long-format rows: one per (ticker, week) since buy.

    Rows: [Week, Date, Ticker, Close Price, Avg Price, Value, Return %].
    The current week uses the portfolio's live price; past weeks use yfinance
    Friday closes backfilled from the buy date.
    """
    now = now or datetime.now()
    holdings = portfolio.get("holdings", {})
    profile = profile or {}
    live_by_ticker = {i["Ticker"]: i for i in portfolio.get("live_data", [])}
    rows = []

    for ticker, pos in holdings.items():
        shares = pos.get("shares", 0)
        tc = pos.get("total_cost", 0) / 100.0
        if shares <= 0 or tc <= 0:
            continue
        avg = tc / shares

        buy_week = _buy_week_for_ticker(profile, ticker)
        start = buy_week if buy_week else (now - pd.Timedelta(days=365))

        weekly = _weekly_close_series(ticker, start)
        live_item = live_by_ticker.get(ticker)

        # Ensure current week present (use live/snapshot price if no history row).
        current_key = _iso_week(now)
        if current_key not in weekly:
            if live_item:
                weekly[current_key] = float(str(live_item["Live Price"]).lstrip("$"))
            else:
                weekly[current_key] = avg

        for week_key in sorted(weekly.index, key=lambda k: k):
            close = weekly[week_key]
            value = shares * close
            ret = ((close - avg) / avg) * 100 if avg else 0.0
            rows.append([
                week_key, "", ticker, round(close, 2), round(avg, 2),
                round(value, 2), round(ret, 2),
            ])

    return rows


def _ensure_tab(service, spreadsheet_id: str, title: str) -> int:
    """Return the sheetId of the named tab, creating it if missing."""
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, ranges=[], fields="sheets(properties(sheetId,title))")
        .execute()
    )
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("title") == title:
            return s["properties"]["sheetId"]
    created = (
        service.spreadsheets()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        )
        .execute()
    )
    sid = created["replies"][0]["addSheet"]["properties"]["sheetId"]
    return sid


def write_weekly_log(
    credentials_dict: dict[str, Any],
    portfolio: dict,
    spreadsheet_id: str | None = None,
    profile: dict | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    """Write (or refresh) the 'Weekly Log' price-history tab.

    Backfills each held ticker's weekly closes since buy and writes them into a
    dedicated tab alongside the snapshot. Rows are replaced wholesale (idempotent
    across repeated clicks within the same week). Profile can store
    `weekly_log_last_exported` to note the last exported ISO week.

    Returns (info, spreadsheetUrl).
    """
    now = now or datetime.now()
    profile = profile or {}
    rows = build_weekly_log_rows(portfolio, profile, now)

    try:
        service = _build_sheets(credentials_dict)
        spreadsheet_id = spreadsheet_id or create_spreadsheet(credentials_dict)
        sid = _ensure_tab(service, spreadsheet_id, WEEKLY_LOG_TAB)

        # Rebuild the tab content (clears any prior rows beyond header).
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=f"'{WEEKLY_LOG_TAB}'!A:G",
        ).execute()
        body = [WEEKLY_LOG_HEADERS] + rows
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{WEEKLY_LOG_TAB}'!A1:G{len(body)}",
            valueInputOption="USER_ENTERED",
            body={"values": body},
        ).execute()

        num_data = len(rows)
        _apply_formatting(service, spreadsheet_id, num_data,
                          sheet_id=sid, headers=WEEKLY_LOG_HEADERS)

        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sid}"
        return {
            "tab": WEEKLY_LOG_TAB,
            "current_week": _iso_week(now),
            "spreadsheet_id": spreadsheet_id,
            "rows": len(rows),
        }, url
    except HttpError as e:
        logger.error(f"Sheets API error (weekly log): {e}")
        raise
