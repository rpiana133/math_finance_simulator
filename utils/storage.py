from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.parse
from threading import Lock
from typing import Any

import requests

GCS_BUCKET_NAME = "math_finance_simulator"
BLOB_PREFIX = "portfolios/"

_logger = logging.getLogger(__name__)

_token_cache: dict[str, Any] = {"token": None, "expires": 0}
_token_lock = Lock()
_profile_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 60.0

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

_SETTINGS_PREFIX = "settings/"
_SETTINGS_CACHE: dict[str, tuple[dict, float]] = {}
_SETTINGS_CACHE_TTL = 60.0


def load_class_settings() -> dict:
    global _SETTINGS_CACHE
    now = time.time()
    cached = _SETTINGS_CACHE.get("class")
    if cached and now - cached[1] < _SETTINGS_CACHE_TTL:
        return cached[0]
    try:
        data = _gcs_read(f"{_SETTINGS_PREFIX}class_settings.json")
        if data is None:
            return {"news_enabled": True}
        settings: dict = json.loads(data)
        _SETTINGS_CACHE["class"] = (settings, now)
        return settings
    except Exception:
        return {"news_enabled": True}


def save_class_settings(settings: dict) -> None:
    global _SETTINGS_CACHE
    try:
        payload = json.dumps(settings)
        _gcs_write(f"{_SETTINGS_PREFIX}class_settings.json", payload)
        _SETTINGS_CACHE["class"] = (settings, time.time())
    except Exception as e:
        _logger.error(f"Failed to save class settings: {e}")


def _safe_email_key(email: str) -> str:
    safe = email.strip().lower()
    if not _EMAIL_RE.match(safe):
        raise ValueError(f"Invalid email format: {email}")
    key_secret = os.environ.get("BLOB_KEY_SECRET", "").encode("utf-8")
    if key_secret:
        return hmac.new(key_secret, safe.encode("utf-8"), "sha256").hexdigest()
    return hashlib.sha256(safe.encode("utf-8")).hexdigest()


def _gcs_creds() -> dict[str, Any]:
    raw = os.environ.get("GCS_SERVICE_ACCOUNT")
    if raw:
        try:
            return json.loads(raw)
        except Exception as e:
            _logger.warning(f"Failed to parse GCS_SERVICE_ACCOUNT env var: {e}")
    raise KeyError("GCS_SERVICE_ACCOUNT environment variable not set")


def _gcs_token() -> str:
    global _token_cache
    with _token_lock:
        if _token_cache["token"] and time.time() < _token_cache["expires"]:
            return _token_cache["token"]
        key_info = _gcs_creds()
    from google.auth import crypt
    from google.auth import jwt as google_jwt

    signer = crypt.RSASigner.from_service_account_info(key_info)
    now = int(time.time())
    jwt_payload = {
        "iss": key_info["client_email"],
        "scope": "https://www.googleapis.com/auth/devstorage.read_write",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }
    assertion = google_jwt.encode(
        signer, jwt_payload, key_id=key_info.get("private_key_id")
    )
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
    )
    try:
        resp.raise_for_status()
        token = resp.json()["access_token"]
        with _token_lock:
            _token_cache["token"] = token
            _token_cache["expires"] = time.time() + 3500
        return token
    except Exception as e:
        _logger.error(f"OAuth2 token error: {e} | Status: {resp.status_code}")
        raise


def _gcs_read(path: str) -> str | None:
    token = _gcs_token()
    resp = requests.get(
        f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text


def _gcs_write(path: str, data: str) -> None:
    token = _gcs_token()
    resp = requests.put(
        f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        data=data.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    resp.raise_for_status()


def _gcs_list(prefix: str) -> list[str]:
    token = _gcs_token()
    resp = requests.get(
        f"https://storage.googleapis.com/storage/v1/b/{GCS_BUCKET_NAME}/o?prefix={urllib.parse.quote(prefix)}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [item["name"] for item in data.get("items", [])]


def load_student_profile(email: str) -> dict | None:
    global _profile_cache
    key = _safe_email_key(email)
    try:
        data = _gcs_read(f"{BLOB_PREFIX}{key}.json")
        profile = None
        if data is not None:
            profile = json.loads(data)

        # Check if the loaded profile is just a fresh empty placeholder
        is_fresh_empty = False
        if profile is not None:
            is_fresh_empty = (
                len(profile.get("holdings", {})) == 0 and
                len(profile.get("history", [])) == 0 and
                profile.get("cash") == 100000
            )

        if data is None or is_fresh_empty:
            # Check old formats for migration
            migrated_path = None
            fallback_data = _gcs_read(f"{BLOB_PREFIX}{email}.json")
            if fallback_data is not None:
                migrated_path = f"{BLOB_PREFIX}{email}.json"
            else:
                fallback_data = _gcs_read(f"{key}.json")
                if fallback_data is not None:
                    migrated_path = f"{key}.json"
                else:
                    fallback_data = _gcs_read(f"{email}.json")
                    if fallback_data is not None:
                        migrated_path = f"{email}.json"

            if fallback_data is not None:
                fallback_profile = json.loads(fallback_data)
                is_fallback_fresh = (
                    len(fallback_profile.get("holdings", {})) == 0 and
                    len(fallback_profile.get("history", [])) == 0 and
                    fallback_profile.get("cash") == 100000
                )
                # Only migrate if the fallback profile actually has history/holdings/cash differences
                if not is_fallback_fresh or data is None:
                    profile = fallback_profile
                    save_student_profile(email, profile)
                    # Delete the legacy blob after migration to prevent duplicates
                    if migrated_path:
                        try:
                            _gcs_delete(migrated_path)
                        except Exception:
                            pass
                    # Sync to running services profile cache to force immediate recovery
                    try:
                        from services.profile import _profiles
                        _profiles[email] = profile
                    except Exception:
                        pass
        return profile
    except Exception as e:
        _logger.error(f"GCS load error for {email}: {e}")
        entry = _profile_cache.get(email)
        if entry and time.time() - entry[1] < _CACHE_TTL:
            return entry[0]
        return None


def save_student_profile(email: str, profile: dict) -> None:
    global _profile_cache
    key = _safe_email_key(email)
    profile["email"] = email
    try:
        payload = json.dumps(profile, indent=4)
    except Exception as e:
        _logger.error(f"JSON serialization error: {e}")
        return
    try:
        _gcs_write(f"{BLOB_PREFIX}{key}.json", payload)
        _profile_cache[email] = (profile, time.time())
    except Exception as e:
        _logger.error(f"GCS save error for {email}: {e}")
        _profile_cache[email] = (profile, time.time())


def _gcs_delete(path: str) -> None:
    token = _gcs_token()
    resp = requests.delete(
        f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()


def delete_student_profile(email: str) -> None:
    global _profile_cache
    key = _safe_email_key(email)
    _gcs_delete(f"{BLOB_PREFIX}{key}.json")
    # Clean up all possible legacy paths
    for legacy_path in [f"{BLOB_PREFIX}{email}.json", f"{key}.json", f"{email}.json"]:
        try:
            _gcs_delete(legacy_path)
        except Exception:
            pass
    _profile_cache.pop(email, None)
    # Clear in-memory profile cache
    try:
        from services.profile import _profiles
        _profiles.pop(email, None)
    except Exception:
        pass


def get_gcs_database() -> dict[str, dict]:
    names = _gcs_list(BLOB_PREFIX)
    db: dict[str, dict] = {}
    for name in names:
        key = name[len(BLOB_PREFIX) : -5]
        data = _gcs_read(name)
        if data:
            db[key] = json.loads(data)
    return db
