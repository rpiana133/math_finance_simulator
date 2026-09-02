from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SHEET_TITLE = "My Stock Tracker"
HEADERS = [
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


def _ensure_headers(service, spreadsheet_id: str) -> None:
    """Write the header row if the first sheet is empty."""
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="A1:I1")
        .execute()
    )
    rows = result.get("values", [])
    if not rows or not rows[0]:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="A1",
            valueInputOption="USER_ENTERED",
            body={"values": [HEADERS]},
        ).execute()


def _existing_weeks(service, spreadsheet_id: str) -> dict[str, int]:
    """Read existing rows and map 'Week' (ISO, e.g. 2026-W36) to its row number.

    Returns {week_key: row_index} for data rows (excludes header).
    """
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="A:I")
        .execute()
    )
    rows = result.get("values", [])
    mapping: dict[str, int] = {}
    for i, row in enumerate(rows):
        if i == 0:
            continue  # header
        if row and row[0]:
            mapping[row[0].strip()] = i + 1  # 1-based row number
    return mapping


def save_weekly_snapshot(
    credentials_dict: dict[str, Any],
    portfolio: dict,
    spreadsheet_id: str | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    """Write the current week's holdings snapshot into the student's tracker sheet.

    If `spreadsheet_id` is provided it is reused; otherwise a new spreadsheet is
    created. The returned info dict includes the spreadsheet_id so the caller can
    persist it for future exports. If a snapshot for the current ISO week already
    exists it is updated in place; otherwise a new row is appended.

    Returns (info, spreadsheetUrl).
    """
    now = now or datetime.now()
    week_key = f"{now.year}-W{now.isocalendar()[1]:02d}"
    date_str = now.strftime("%Y-%m-%d")

    holdings = portfolio.get("holdings", {})
    live = portfolio.get("live_data", [])

    live_by_ticker = {item["Ticker"]: item for item in live}

    cells = []
    for ticker, pos in holdings.items():
        shares = pos.get("shares", 0)
        if shares <= 0:
            continue
        tc = pos.get("total_cost", 0) / 100.0
        avg = tc / shares if shares else 0.0
        lp = live_by_ticker.get(ticker)
        live_price = float(lp["Live Price"].lstrip("$")) if lp else 0.0
        value = shares * live_price
        cells.append(
            f"{ticker}:{shares:.4f}:{avg:.2f}:{live_price:.2f}:{value:.2f}"
        )
    holdings_summary = " | ".join(cells) if cells else ""

    total = portfolio.get("total", 0.0)
    row = [week_key, date_str, holdings_summary, "", "", "", "", "", f"{total:.2f}"]

    try:
        service = _build_sheets(credentials_dict)
        spreadsheet_id = spreadsheet_id or create_spreadsheet(credentials_dict)
        _ensure_headers(service, spreadsheet_id)

        weeks = _existing_weeks(service, spreadsheet_id)
        if week_key in weeks:
            row_num = weeks[week_key]
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"A{row_num}:I{row_num}",
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            ).execute()
            action = "updated"
        else:
            last_row = max(weeks.values()) if weeks else 1
            new_row = last_row + 1
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"A{new_row}:I{new_row}",
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            ).execute()
            action = "appended"

        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        return {
            "action": action,
            "week": week_key,
            "spreadsheet_id": spreadsheet_id,
        }, url
    except HttpError as e:
        logger.error(f"Sheets API error: {e}")
        raise
