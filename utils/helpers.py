import os
from datetime import datetime
from typing import Union

STARTING_CASH_CENTS: int = 100000


def _cents(dollars: float) -> int:
    return int(round(dollars * 100))


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"{name} environment variable must be set")
    return val


def _fmt(cents) -> str:
    cents = int(cents)
    sign = "-" if cents < 0 else ""
    abs_c = abs(cents)
    return f"{sign}${abs_c // 100:,}.{abs_c % 100:02d}"


def _relative_time(ts: Union[str, int]) -> str:
    if isinstance(ts, str):
        ts = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
    else:
        ts = int(ts)
    diff = int(datetime.now().timestamp()) - ts
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    if diff < 604800:
        return f"{diff // 86400}d ago"
    return datetime.fromtimestamp(ts).strftime("%b %d")
