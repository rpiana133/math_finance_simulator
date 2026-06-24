import json
import logging
import os
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

_logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/classroom.coursework.students',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]

_teacher_emails_raw = os.environ.get("TEACHER_EMAILS", "")
if _teacher_emails_raw:
    TEACHER_EMAILS = [e.strip() for e in _teacher_emails_raw.split(",")]
else:
    TEACHER_EMAILS = ["rpiana@stjohnsguam.com"]
    _logger.warning("TEACHER_EMAILS env var not set, using hardcoded default")


def get_redirect_uri():
    return os.environ.get("REDIRECT_URI", "http://localhost:8080/callback")


def get_client_config():
    raw = os.environ.get("GOOGLE_CLIENT_SECRET")
    if raw:
        return json.loads(raw)
    raise KeyError("GOOGLE_CLIENT_SECRET environment variable not set")


def get_auth_url(redirect_uri=None):
    client_config = get_client_config()
    flow = Flow.from_client_config(
        client_config, scopes=SCOPES,
        redirect_uri=redirect_uri or get_redirect_uri()
    )
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return auth_url


def exchange_code(code, redirect_uri=None):
    client_config = get_client_config()
    flow = Flow.from_client_config(
        client_config, scopes=SCOPES,
        redirect_uri=redirect_uri or get_redirect_uri()
    )
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    flow.fetch_token(code=code)

    user_info_service = build('oauth2', 'v2', credentials=flow.credentials)
    user_info = user_info_service.userinfo().get().execute()
    return user_info


def is_teacher(email):
    return email in TEACHER_EMAILS
