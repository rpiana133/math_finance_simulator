import streamlit as st
import json
import time
import urllib.parse
import requests
from google.oauth2 import service_account
from google.auth import crypt
from google.cloud import storage

GCS_BUCKET_NAME = "math_finance_simulator"
BLOB_PREFIX = "portfolios/"

def _gcs_creds():
    raw = st.secrets.get("GCS_SERVICE_ACCOUNT")
    if raw:
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            pass
    # Build from individual secret fields
    fields = {
        "type": "service_account",
        "project_id": st.secrets.get("project_id", ""),
        "private_key_id": st.secrets.get("private_key_id", ""),
        "private_key": st.secrets.get("private_key", ""),
        "client_email": st.secrets.get("client_email", ""),
        "client_id": st.secrets.get("client_id", ""),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": st.secrets.get("client_x509_cert_url", ""),
        "universe_domain": "googleapis.com"
    }
    return fields

@st.cache_resource(ttl=1500)
def _gcs_token():
    key_info = _gcs_creds()
    signer = crypt.RSASigner.from_service_account_info(key_info)
    now = int(time.time())
    jwt_payload = {
        "iss": key_info["client_email"],
        "scope": "https://www.googleapis.com/auth/devstorage.read_write",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now
    }
    from google.auth import jwt as google_jwt
    assertion = google_jwt.encode(signer, jwt_payload, key_id=key_info.get("private_key_id"))
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion
    })
    try:
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as e:
        st.error(f"OAuth2 token error: {e} | Status: {resp.status_code} | Body: {resp.text[:500]}")
        raise

def _gcs_read(path):
    token = _gcs_token()
    resp = requests.get(f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text

def _gcs_write(path, data):
    token = _gcs_token()
    resp = requests.put(f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        data=data.encode('utf-8'), headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
    resp.raise_for_status()

def _gcs_exists(path):
    token = _gcs_token()
    resp = requests.get(f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{urllib.parse.quote(path)}",
        headers={"Authorization": f"Bearer {token}"})
    return resp.status_code == 200

def _gcs_list(prefix):
    token = _gcs_token()
    resp = requests.get(
        f"https://storage.googleapis.com/storage/v1/b/{GCS_BUCKET_NAME}/o?prefix={urllib.parse.quote(prefix)}",
        headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [item["name"] for item in data.get("items", [])]

def get_gcs_client():
    key_info = json.loads(st.secrets["GCS_SERVICE_ACCOUNT"])
    creds = service_account.Credentials.from_service_account_info(key_info)
    client = storage.Client(credentials=creds, project=key_info.get("project_id"))
    return client

def load_student_profile(email):
    try:
        data = _gcs_read(f"{BLOB_PREFIX}{email}.json")
        if data is None:
            # Fallback: check without prefix
            data = _gcs_read(f"{email}.json")
            if data is not None:
                profile = json.loads(data)
                save_student_profile(email, profile)
                return profile
            return None
        return json.loads(data)
    except Exception as e:
        st.error(f"GCS load error: {e}")
        if 'profiles_cache' not in st.session_state:
            st.session_state.profiles_cache = {}
        return st.session_state.profiles_cache.get(email)

def save_student_profile(email, profile):
    try:
        payload = json.dumps(profile, indent=4)
    except Exception as e:
        st.error(f"JSON serialization error: {e}")
        return
    try:
        _gcs_write(f"{BLOB_PREFIX}{email}.json", payload)
    except Exception as e:
        st.error(f"GCS save error: {e}")
        if 'profiles_cache' not in st.session_state:
            st.session_state.profiles_cache = {}
        st.session_state.profiles_cache[email] = profile

def get_gcs_database():
    """Fetch all student portfolios from GCS by listing per-student files."""
    names = _gcs_list(BLOB_PREFIX)
    db = {}
    for name in names:
        email = name[len(BLOB_PREFIX):-5]  # strip prefix + .json
        data = _gcs_read(name)
        if data:
            db[email] = json.loads(data)
    return db
