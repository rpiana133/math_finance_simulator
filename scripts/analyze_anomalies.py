"""Analyze student accounts for anomalies using the app's own GCS read paths.

Checks the DETERMINISTIC stored ledger for each profile (no live price fetches):
  - unsettled cash that exceeds the logged sell history
  - holdings cost basis that exceeds logged buy totals
  - trade-history balance (buys vs. sells vs. cash)
Net worth is computed with the app's own `_portfolio()` so figures match the app.

Run from the repo root with:
    GCS_SERVICE_ACCOUNT=... BLOB_KEY_SECRET=... python3 scripts/analyze_anomalies.py
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("analyze")

from services.profile import _clean_dust_holdings, _migrate_profile, _portfolio
from utils.helpers import STARTING_CASH_CENTS
from utils.storage import get_gcs_database

TEACHER = "rpiana@stjohnsguam.com"


def main():
    if not os.environ.get("GCS_SERVICE_ACCOUNT") or not os.environ.get("BLOB_KEY_SECRET"):
        print("Set GCS_SERVICE_ACCOUNT and BLOB_KEY_SECRET env vars (from Secret Manager).", file=sys.stderr)
        return 1

    db = get_gcs_database()
    profiles = []
    for _k, p in db.items():
        p = _migrate_profile(p)
        _clean_dust_holdings(p)
        email = (p.get("email") or "").strip().lower()
        if not email or email == TEACHER:
            continue
        profiles.append((email, p))

    suspicious = []
    for email, p in profiles:
        cash = p.get("cash", STARTING_CASH_CENTS)
        unsettled = p.get("unsettled_cash", 0)
        deposits = p.get("total_deposits", 0)
        history = p.get("history", [])
        unsettled_entries = p.get("unsettled_entries", [])

        buys = sum(h.get("total", 0) for h in history if h.get("type") in ("Buy", "buy"))
        sells = sum(h.get("total", 0) for h in history if h.get("type") in ("Sell", "sell"))
        hold_cost = sum(pos.get("total_cost", 0) for pos in p.get("holdings", {}).values()) / 100.0
        ue_sum = sum(e.get("amount", 0) for e in unsettled_entries)

        nw = _portfolio(p)["total"]
        capital = (STARTING_CASH_CENTS + deposits) / 100.0
        ret = ((nw - capital) / capital) * 100 if capital else 0.0

        flags = []
        # 1) Unsettled cash with no sell history (money that appeared from nowhere).
        if unsettled > 0 and sells == 0:
            flags.append(f"UNSETTLED ${unsettled/100:.2f} with ZERO sell history")
        # 2) Unsettled cash more than 1.5x the total logged sells.
        elif unsettled > 0 and unsettled / 100.0 > sells * 1.5 + 1:
            flags.append(f"UNSETTLED ${unsettled/100:.2f} >> sells ${sells:.2f}")
        # 3) Unsettled-entry sum does not reconcile with unsettled_cash.
        if unsettled and abs(ue_sum - unsettled) > 1:
            flags.append(f"UE-SUM-MISMATCH entries=${ue_sum/100:.2f} vs unsettled=${unsettled/100:.2f}")
        # 4) Holdings cost basis far above total logged buys.
        if buys > 0 and hold_cost > buys * 1.5 + 1:
            flags.append(f"HOLD-COST ${hold_cost:.0f} >> buys ${buys:.0f}")

        if flags:
            suspicious.append(
                {
                    "email": email,
                    "name": p.get("name", "?"),
                    "nw": nw,
                    "ret": ret,
                    "trades": len(history),
                    "cash": cash / 100.0,
                    "unsettled": unsettled / 100.0,
                    "hold_cost": hold_cost,
                    "buys": buys,
                    "sells": sells,
                    "deposits": deposits / 100.0,
                    "flags": " | ".join(flags),
                }
            )

    suspicious.sort(key=lambda r: -r["nw"])
    print("=== LEDGER ANOMALIES (deterministic, no live prices) ===")
    for r in suspicious:
        print(
            f"{r['email']:<42} NW ${r['nw']:>10,.2f} ret {r['ret']:>9.1f}%  "
            f"trades {r['trades']:<3} cash ${r['cash']:>9,.2f} unsettled ${r['unsettled']:>9,.2f} "
            f"holdcost ${r['hold_cost']:>9,.2f} buys ${r['buys']:>8,.2f} sells ${r['sells']:>8,.2f} "
            f"dep ${r['deposits']:>8,.2f}"
        )
        print(f"    -> {r['flags']}")

    print(f"\nTotal students: {len(profiles)}  Anomalies: {len(suspicious)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
