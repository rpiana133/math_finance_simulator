#!/usr/bin/env python3
"""Force-sell a delisted ticker from every student profile and refund them.

Used to remove a ticker from the simulator (e.g. one with broken/static price
data) and return students what they originally paid for it, so no student loses
money when the ticker disappears.

Each affected profile gets:
  - the holding removed from ``holdings``
  - ``cash`` credited the full ``total_cost`` (in cents) of the removed holding
  - a ``Sell`` history entry logged (type "Sell", price = average cost) so the
    ledger stays consistent with the anomaly checker (buys == sells + holdings)

Run from the repo root with:
    GCS_SERVICE_ACCOUNT=... BLOB_KEY_SECRET=... \
        python3 scripts/refund_remove_ticker.py TICKER [TICKER ...]

Prints before/after per student and a summary. Requires write access to the
same GCS bucket the app uses (via GCS_SERVICE_ACCOUNT), so run it manually,
not inside the deployed container.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.profile import _migrate_profile, _portfolio
from utils.storage import get_gcs_database, save_student_profile

TEACHER = "rpiana@stjohnsguam.com"


def main() -> int:
    tickers = [t.strip().upper() for t in sys.argv[1:] if t.strip()]
    if not tickers:
        print("Usage: refund_remove_ticker.py TICKER [TICKER ...]", file=sys.stderr)
        return 1
    if not os.environ.get("GCS_SERVICE_ACCOUNT") or not os.environ.get("BLOB_KEY_SECRET"):
        print("Set GCS_SERVICE_ACCOUNT and BLOB_KEY_SECRET env vars.", file=sys.stderr)
        return 1

    db = get_gcs_database()
    total_profiles = 0
    for target in tickers:
        affected = []
        for _k, p in db.items():
            p = _migrate_profile(p)
            email = (p.get("email") or "").strip().lower()
            if not email or email == TEACHER:
                continue
            pos = p.get("holdings", {}).get(target)
            if not pos or pos.get("shares", 0) <= 0 or pos.get("total_cost", 0) <= 0:
                continue
            shares = pos.get("shares", 0)
            cost_cents = pos.get("total_cost", 0)
            avg_price = (cost_cents / 100.0) / shares if shares else 0.0

            before = _portfolio(p)["total"]
            p["cash"] = p.get("cash", 0) + cost_cents
            del p["holdings"][target]
            p.setdefault("history", []).append(
                {
                    "type": "Sell",
                    "ticker": target,
                    "shares": round(shares, 4),
                    "price": round(avg_price, 2),
                    "total": round(cost_cents / 100.0, 2),
                    "cost_basis": round(cost_cents / 100.0, 2),
                    "tax": 0.0,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            )
            save_student_profile(email, p)
            after = _portfolio(p)["total"]
            affected.append((email, shares, cost_cents / 100.0, before, after))

        total_profiles += len(affected)
        print(f"=== {target}: force-refunded {len(affected)} student(s) ===")
        for email, shares, refund, before, after in affected:
            print(
                f"  {email:<42s} shares={shares:>8.4f} refund=${refund:>8.2f} "
                f"networth ${before:>10.2f} -> ${after:>10.2f}"
            )
    print(f"\nTotal students refunded across all tickers: {total_profiles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
