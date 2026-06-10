import json
import os
import time
import logging
import urllib.parse
import requests

GCS_BUCKET_NAME = "math_finance_simulator"
BLOB_PREFIX = "portfolios/"

_logger = logging.getLogger(__name__)

_token_cache = {"token": None, "expires": 0}
_profile_cache = {}


def _gcs_creds():
    raw = os.environ.get("GCS_SERVICE_ACCOUNT")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    if os.path.exists("math-finance-simulator-51d674093aa1.json"):
        with open("math-finance-simulator-51d674093aa1.json", "r") as f:
            return json.load(f)
    raise KeyError("GCS_SERVICE_ACCOUNT environment variable not set (and no JSON key file found)")


def _gcs_token():
    global _token_cache
    if _token_cache["token"] and time.time() < _token_cache["expires"]:
        return _token_cache["token"]
    key_info = _gcs_creds()
    from google.auth import crypt, jwt as google_jwt
    signer = crypt.RSASigner.from_service_account_info(key_info)
    now = int(time.time())
    jwt_payload = {
        "iss": key_info["client_email"],
        "scope": "https://www.googleapis.com/auth/devstorage.read_write",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now
    }
    assertion = google_jwt.encode(signer, jwt_payload, key_id=key_info.get("private_key_id"))
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion
    })
    try:
        resp.raise_for_status()
        token = resp.json()["access_token"]
        _token_cache["token"] = token
        _token_cache["expires"] = time.time() + 3500
        return token
    except Exception as e:
        _logger.error(f"OAuth2 token error: {e} | Status: {resp.status_code}")
        raise


def _gcs_read(path):
    token = _gcs_token()
    resp = requests.get(
        f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text


def _gcs_write(path, data):
    token = _gcs_token()
    resp = requests.put(
        f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        data=data.encode('utf-8'),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    resp.raise_for_status()


def _gcs_list(prefix):
    token = _gcs_token()
    resp = requests.get(
        f"https://storage.googleapis.com/storage/v1/b/{GCS_BUCKET_NAME}/o?prefix={urllib.parse.quote(prefix)}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [item["name"] for item in data.get("items", [])]


def load_student_profile(email):
    global _profile_cache
    try:
        data = _gcs_read(f"{BLOB_PREFIX}{email}.json")
        if data is None:
            data = _gcs_read(f"{email}.json")
            if data is not None:
                profile = json.loads(data)
                save_student_profile(email, profile)
                return profile
            return None
        return json.loads(data)
    except Exception as e:
        _logger.error(f"GCS load error for {email}: {e}")
        return _profile_cache.get(email)


def save_student_profile(email, profile):
    global _profile_cache
    try:
        payload = json.dumps(profile, indent=4)
    except Exception as e:
        _logger.error(f"JSON serialization error: {e}")
        return
    try:
        _gcs_write(f"{BLOB_PREFIX}{email}.json", payload)
        _profile_cache[email] = profile
    except Exception as e:
        _logger.error(f"GCS save error for {email}: {e}")
        _profile_cache[email] = profile


def get_gcs_database():
    names = _gcs_list(BLOB_PREFIX)
    db = {}
    for name in names:
        email = name[len(BLOB_PREFIX):-5]
        data = _gcs_read(name)
        if data:
            db[email] = json.loads(data)
    return db
