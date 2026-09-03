#!/usr/bin/env python3
"""One-off: list all students + net worth + return, sorted by the leading
number in each student's email username (ascending).

Reads student profiles from the app's GCS bucket and writes a CSV report.

Prerequisites (set these env vars or the script will exit):
    GCS_SERVICE_ACCOUNT   JSON string of the GCS service account (from Secret
                          Manager secret GCS_SERVICE_ACCOUNT)
    BLOB_KEY_SECRET       HMAC blob-key secret (Secret Manager BLOB_KEY_SECRET)
    FINNHUB_API_KEY       optional; only used if not provided (news is not
                          needed for this report, safe to omit)

Usage:
    export GCS_SERVICE_ACCOUNT="$(
        gcloud secrets versions access latest --secret=GCS_SERVICE_ACCOUNT --project=math-finance-simulator
    )"
    export BLOB_KEY_SECRET="$(
        gcloud secrets versions access latest --secret=BLOB_KEY_SECRET --project=math-finance-simulator
    )"
    python3 scripts/student_report.py              # writes students_report.csv (default)

Output CSV columns: Email,Name,Net Worth,Return
Students are sorted ascending by the numeric ID at the start of their username
(e.g. "2027jdoe@..." sorts by 2027, lowest first). Usernames with no leading
number are placed after all numbered entries.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import sys

# Force the repo root onto the import path so `utils.*` / `services.*` resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("student_report")

_LEADING_NUM = re.compile(r"^(\d+)")
TEACHER_EMAIL = "rpiana@stjohnsguam.com"


def _email_sort_key(email: str):
    """Return a sort key descending-priority: numbered usernames first.

    (0, int) for usernames starting with a number (ascending by that number),
    (1, 0) for everything else so they fall after all numbered entries.
    """
    local = (email or "").split("@")[0]
    m = _LEADING_NUM.match(local)
    if m:
        return (0, int(m.group(1)))
    return (1, 0)


def _student_email(profile: dict) -> str | None:
    email = (profile.get("email") or "").strip()
    return email.lower() if email else None


def compute_rows() -> list[dict]:
    from services.profile import _clean_dust_holdings, _migrate_profile
    from utils.helpers import STARTING_CASH_CENTS
    from utils.market import fetch_stock_market_data
    from utils.storage import get_gcs_database

    db = get_gcs_database()
    if not db:
        logger.warning("No student profiles found in GCS.")
        return []

    db.pop(TEACHER_EMAIL, None)

    # Migrate + clean every profile up front so math matches the app.
    profiles = []
    for _key, p in db.items():
        p = _migrate_profile(p)
        _clean_dust_holdings(p)
        email = _student_email(p)
        if not email:
            logger.warning(f"Skipping profile with no email (key={_key!r})")
            continue
        profiles.append((email, p))

    # Batch-fetch all unique tickers' live prices in parallel (like the app).
    all_tickers = {t for _e, p in profiles for t in p.get("holdings", {})}
    price_map: dict[str, float] = {}
    if all_tickers:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(fetch_stock_market_data, t): t for t in all_tickers}
            for fut in as_completed(futs, timeout=60):
                t = futs[fut]
                try:
                    price = fut.result(timeout=10)[0]
                except Exception:
                    continue
                if price is not None:
                    price_map[t] = price

    rows = []
    for email, p in profiles:
        mv = 0.0
        for t, pos in p.get("holdings", {}).items():
            pr = price_map.get(t)
            if pr is not None and pos.get("shares", 0) > 0:
                mv += pos["shares"] * pr
        cash = p.get("cash", STARTING_CASH_CENTS)
        unsettled = p.get("unsettled_cash", 0)
        nw = ((cash + unsettled) / 100) + mv
        capital = (STARTING_CASH_CENTS + p.get("total_deposits", 0)) / 100
        ret = ((nw - capital) / capital) * 100 if capital else 0.0
        rows.append(
            {
                "email": email,
                "name": p.get("name", "Student"),
                "net_worth": round(nw, 2),
                "return": round(ret, 2),
            }
        )

    rows.sort(key=lambda r: _email_sort_key(r["email"]))
    return rows


def write_csv(rows: list[dict], out_path: str) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Email", "Name", "Net Worth", "Return"])
        for r in rows:
            writer.writerow([r["email"], r["name"], f"{r['net_worth']:.2f}", f"{r['return']:.2f}"])


def main() -> int:
    if not os.environ.get("GCS_SERVICE_ACCOUNT"):
        print("Missing GCS_SERVICE_ACCOUNT env var.", file=sys.stderr)
        print("  gcloud secrets versions access latest --secret=GCS_SERVICE_ACCOUNT --project=math-finance-simulator", file=sys.stderr)
        return 1
    if not os.environ.get("BLOB_KEY_SECRET"):
        print("Missing BLOB_KEY_SECRET env var.", file=sys.stderr)
        print("  gcloud secrets versions access latest --secret=BLOB_KEY_SECRET --project=math-finance-simulator", file=sys.stderr)
        return 1

    out_path = sys.argv[1] if len(sys.argv) > 1 else "students_report.csv"
    rows = compute_rows()
    write_csv(rows, out_path)
    print(f"Wrote {len(rows)} student(s) to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
