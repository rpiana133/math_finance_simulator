import json
import os
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/classroom.coursework.students',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]

TEACHER_EMAIL = "rpiana@stjohnsguam.com"


def get_redirect_uri():
    return os.environ.get("REDIRECT_URI", "http://localhost:8080/callback")


def get_client_config():
    raw = os.environ.get("GOOGLE_CLIENT_SECRET")
    if raw:
        return json.loads(raw)
    if os.path.exists("client_secret.json"):
        with open("client_secret.json", "r") as f:
            return json.load(f)
    raise KeyError("GOOGLE_CLIENT_SECRET environment variable not set")


def get_auth_url():
    client_config = get_client_config()
    flow = Flow.from_client_config(
        client_config, scopes=SCOPES,
        redirect_uri=get_redirect_uri()
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
    return email == TEACHER_EMAIL
