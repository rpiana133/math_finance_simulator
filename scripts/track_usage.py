#!/usr/bin/env python3
"""Track Cloud Run usage for Math Finance Simulator and project a monthly cost.

Queries Cloud Monitoring for a date range and aggregates, per hour (UTC-aligned):
  - billable instance time  (run.googleapis.com/container/billable_instance_time, seconds)
  - request count           (run.googleapis.com/request_count, count)

Outputs CSV (hourly + daily) and a raw JSON snapshot, then prints a weekday/weekend
split and a Cloud Run cost projection for the range. The projection reports BOTH
the raw billable usage and the estimated billed amount after the monthly free tier
(180,000 vCPU-sec / 360,000 GiB-sec / 2M requests) is subtracted.

The projection uses the running service's billing shape: request-based billing,
us-east1 region, 1 vCPU, 0.5 GiB memory. Pricing values are editable constants
below (verify against the current Cloud Run pricing page before relying on the
dollar figures).

Prerequisites:
  - gcloud authenticated (``gcloud auth login`` / ``gcloud auth application-default``);
    the script shells out to ``gcloud auth print-access-token``.
  - PROJECT defaults to the active gcloud project (math-finance-simulator).

Usage (Guam/Local dates, inclusive of start day, end day earliest ~now):
    python3 scripts/track_usage.py --start 2026-09-01 --end 2026-09-30

    # historical first days only (one-off):
    python3 scripts/track_usage.py --start 2026-09-01 --end 2026-09-04

All timestamps are handled realistically: local dates are interpreted as Guam
time (UTC+10, no DST) and converted to UTC for the query. Output dir defaults to
``data/usage``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Guam is UTC+10 year-round (no DST).
GUAM_UTC_OFFSET = dt.timedelta(hours=10)

PROJECT = os.environ.get("GCP_PROJECT") or "math-finance-simulator"
MONITORING = f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries"

DEFAULT_OUT_DIR = os.path.join("data", "usage")
DEFAULT_REGION = "us-east1"

# --- Billing constants (request-based billing, us-east1) ----------------------
# Verify these against the live Cloud Run pricing page before trusting dollars.
# 1 vCPU, 0.5 GiB memory, request-based (per-100ms, minimum 100ms/request).
BILLABLE_VCPU = 1.0
BILLABLE_MEM_GIB = 0.5
SECONDS_PER_HOUR = 3600.0

# Cloud Run charges per-SECOND (not per-hour). us-east1 request-based rates:
VCPU_PER_SECOND_USD = 0.00002400  # $/vCPU-second
MEM_PER_GIB_SECOND_USD = 0.00000250  # $/GiB-second

# Monthly free tier (request-based), applied per billing account / month:
FREE_VCPU_SECONDS = 180_000        # = 50 vCPU-hours at 1 vCPU
FREE_MEM_GIB_SECONDS = 360_000     # = 200 GiB-hours at 0.5 GiB
FREE_REQUESTS_MONTH = 2_000_000
COST_PER_1000_REQUESTS = 0.40  # $/1000 requests above free tier (us-east1)

METRICS = {
    "billable_seconds": "run.googleapis.com/container/billable_instance_time",
    "requests": "run.googleapis.com/request_count",
}


def _token() -> str:
    out = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not out:
        raise RuntimeError("gcloud returned an empty access token")
    return out


def _fetch_hourly(metric_type: str, start_utc: str, end_utc: str, token: str):
    query = urllib.parse.urlencode(
        {
            "filter": f'metric.type = "{metric_type}"',
            "interval.startTime": start_utc,
            "interval.endTime": end_utc,
            "aggregation.alignmentPeriod": "3600s",
            "aggregation.perSeriesAligner": "ALIGN_SUM",
            # Roll all revisions into one aggregate series (grouped by service)
            # so the query returns a single total (no per-revision rows to
            # double-count). crossSeriesReducer.REDUCE_SUM is required alongside
            # groupByFields.
            "aggregation.crossSeriesReducer": "REDUCE_SUM",
            "aggregation.groupByFields": "resource.label.service_name",
            "view": "FULL",
        }
    )
    req = urllib.request.Request(
        f"{MONITORING}?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Monitoring API error {e.code}: {e.read().decode()}") from e

    points = {}
    for ts in data.get("timeSeries", []):
        for pt in ts.get("points", []):
            start = pt["interval"]["startTime"]  # e.g. 2026-09-01T04:00:00Z
            v = pt["value"]
            val = float(v.get("doubleValue") or v.get("int64Value") or 0)
            # Multiple revisions / aliased series can share the same hour bucket.
            # Sum across all of them so each bucket is counted exactly once.
            points[start] = points.get(start, 0.0) + val
    return points


def _guam_to_utc(date: dt.date) -> dt.datetime:
    return dt.datetime.combine(date, dt.time(0, 0)) - GUAM_UTC_OFFSET


def _utc_to_guam(utc: dt.datetime) -> dt.datetime:
    return utc + GUAM_UTC_OFFSET


def _iso_utc(d: dt.datetime) -> str:
    # Cloud Monitoring wants RFC3339 in UTC ("Z").
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="Start date (Guam), YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="End date (Guam), YYYY-MM-DD inclusive")
    ap.add_argument("--out", default=DEFAULT_OUT_DIR, help="Output directory (default data/usage)")
    ap.add_argument("--json", default=None, help="Optional explicit JSON file path")
    args = ap.parse_args()

    start_d = dt.date.fromisoformat(args.start)
    end_d = dt.date.fromisoformat(args.end)
    if end_d < start_d:
        print("--end must be >= --start", file=sys.stderr)
        return 1
    # Query through end of the inclusive end day.
    end_utc = _guam_to_utc(end_d + dt.timedelta(days=1))

    os.makedirs(args.out, exist_ok=True)
    token = _token()

    hourly = {}  # (date_guam, hour) -> {metric: value}
    for key, mtype in METRICS.items():
        pts = _fetch_hourly(mtype, _iso_utc(_guam_to_utc(start_d)), _iso_utc(end_utc), token)
        for start_str, val in pts.items():
            # start_str is the UTC hour bucket start; convert to Guam date/hour.
            utc = dt.datetime.strptime(start_str, "%Y-%m-%dT%H:%M:%SZ")
            guam = _utc_to_guam(utc)
            key_t = (guam.date(), guam.hour)
            hourly.setdefault(key_t, {})[key] = val

    # --- Build hourly CSV ------------------------------------------------------
    hourly_path = os.path.join(args.out, f"hourly_{args.start}_to_{args.end}.csv")
    with open(hourly_path, "w", newline="", encoding="utf-8") as f:
        f.write("Date (Guam),Hour (Guam),Billable Seconds,Requests,Billable Hours\n")
        for (date_g, hour), vals in sorted(hourly.items()):
            bsec = vals.get("billable_seconds", 0)
            req = vals.get("requests", 0)
            f.write(f"{date_g.isoformat()},{hour:02d},{bsec:g},{req:g},{bsec/3600.0:.4f}\n")

    # --- Build daily aggregation ----------------------------------------------
    daily = []  # {date, weekday, weekend, billable_hours, requests}
    by_date = {}
    for (date_g, _hour), vals in hourly.items():
        d = by_date.setdefault(date_g, {"billable_seconds": 0.0, "requests": 0.0})
        d["billable_seconds"] += vals.get("billable_seconds", 0)
        d["requests"] += vals.get("requests", 0)

    for date_g in sorted(by_date):
        d = by_date[date_g]
        wd = date_g.weekday()  # Mon=0..Sun=6
        weekend = wd >= 5
        daily.append(
            {
                "date": date_g.isoformat(),
                "weekday": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd],
                "weekend": weekend,
                "billable_hours": d["billable_seconds"] / 3600.0,
                "requests": d["requests"],
            }
        )

    daily_path = os.path.join(args.out, f"daily_{args.start}_to_{args.end}.csv")
    with open(daily_path, "w", newline="", encoding="utf-8") as f:
        f.write("Date (Guam),Weekday,Weekend,Billable Hours,Requests\n")
        for r in daily:
            f.write(f"{r['date']},{r['weekday']},{'1' if r['weekend'] else '0'},{r['billable_hours']:.4f},{r['requests']:g}\n")

    # --- Raw JSON snapshot ----------------------------------------------------
    json_path = (
        args.json or os.path.join(args.out, f"usage_{args.start}_to_{args.end}.json")
    )
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"daily": daily, "hourly": sorted(
            [(d.isoformat(), h, v) for (d, h), v in hourly.items()]
        )}, f, indent=1)

    # --- Totals & weekday/weekend split ---------------------------------------
    tot_h = sum(r["billable_hours"] for r in daily)
    tot_req = sum(r["requests"] for r in daily)
    wd_h = sum(r["billable_hours"] for r in daily if not r["weekend"])
    we_h = sum(r["billable_hours"] for r in daily if r["weekend"])
    wd_req = sum(r["requests"] for r in daily if not r["weekend"])
    we_req = sum(r["requests"] for r in daily if r["weekend"])

    print(f"\n=== USAGE {args.start} -> {args.end} (Guam) ===")
    print(f"Days covered : {len(daily)}  (weekdays {sum(1 for r in daily if not r['weekend'])}, weekends {sum(1 for r in daily if r['weekend'])})")
    print(f"Total billable hours : {tot_h:,.1f}  (weekday {wd_h:,.1f} / weekend {we_h:,.1f})")
    print(f"Total requests       : {tot_req:,.0f}  (weekday {wd_req:,.0f} / weekend {we_req:,.0f})")

    # --- Cost projection (free tier subtracted) --------------------------------
    # Note: billable_instance_time is "<= 1 instance busy" seconds per hour, so
    # per-second vCPU usage = billable_seconds x vCPU (and same for memory).
    vcpu_secs = tot_h * SECONDS_PER_HOUR * BILLABLE_VCPU
    mem_gib_secs = tot_h * SECONDS_PER_HOUR * BILLABLE_MEM_GIB
    billed_vcpu_secs = max(0, vcpu_secs - FREE_VCPU_SECONDS)
    billed_mem_gib_secs = max(0, mem_gib_secs - FREE_MEM_GIB_SECONDS)
    vcpu_cost = billed_vcpu_secs * VCPU_PER_SECOND_USD
    mem_cost = billed_mem_gib_secs * MEM_PER_GIB_SECOND_USD
    billable_req = max(0, tot_req - FREE_REQUESTS_MONTH)
    req_cost = (billable_req / 1000.0) * COST_PER_1000_REQUESTS
    total = vcpu_cost + mem_cost + req_cost

    print("\n=== COST PROJECTION (request-based, us-east1, free tier applied) ===")
    print(f"vCPU    : {vcpu_secs:,.0f} sec  - {FREE_VCPU_SECONDS:,} free  = {billed_vcpu_secs:,.0f} billed sec  -> ${vcpu_cost:,.4f}")
    print(f"Memory  : {mem_gib_secs:,.0f} GiB-s  - {FREE_MEM_GIB_SECONDS:,} free  = {billed_mem_gib_secs:,.0f} billed GiB-s -> ${mem_cost:,.4f}")
    print(f"Requests: {tot_req:,.0f}  - {FREE_REQUESTS_MONTH:,} free  = {billable_req:,.0f} billed        -> ${req_cost:,.4f}")
    print(f"Est. Cloud Run compute total (this window) : ${total:,.4f}")
    print("(Excludes storage / Secret Manager / builds / egress; startup CPU boost + cold starts add a little.)")

    print(f"\nWrote: {hourly_path}")
    print(f"       {daily_path}")
    print(f"       {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
