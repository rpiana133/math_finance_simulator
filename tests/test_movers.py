import os

os.environ.setdefault("TEACHER_EMAILS", "rpiana@stjohnsguam.com")
os.environ.setdefault("GOOGLE_HD", "stjohnsguam.com")
os.environ.setdefault("BLOB_KEY_SECRET", "test-secret-do-not-use")

from utils.market import movers_load_action


def _cache(loaded=False, ts=0.0, loading=False):
    return {"data": [], "loaded": loaded, "ts": ts, "loading": loading}


def test_movers_action_refresh_when_fresh():
    now = 1000.0
    cache = _cache(loaded=True, ts=900.0)
    assert movers_load_action(cache, now, 300.0) == "refresh"


def test_movers_action_refresh_not_fresh_loaded():
    now = 1000.0
    cache = _cache(loaded=True, ts=500.0)
    assert movers_load_action(cache, now, 300.0) == "fetch"


def test_movers_action_fetch_when_unloaded_idle():
    cache = _cache(loaded=False, loading=False)
    assert movers_load_action(cache, 1000.0, 300.0) == "fetch"


def test_movers_action_wait_when_loading_flag_held():
    cache = _cache(loaded=False, loading=True)
    assert movers_load_action(cache, 1000.0, 300.0) == "wait"


def test_movers_action_never_dead_ends_on_wedge_state():
    now = 1000.0
    cache = _cache(loaded=False, ts=0.0, loading=True)
    action = movers_load_action(cache, now, 300.0)
    assert action in {"refresh", "wait", "fetch"}
    assert action == "wait"