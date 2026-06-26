from __future__ import annotations

import json
import logging
import os
from typing import Any

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

_logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

_teacher_emails_raw = os.environ.get("TEACHER_EMAILS")
if _teacher_emails_raw:
    TEACHER_EMAILS = [e.strip() for e in _teacher_emails_raw.split(",")]
else:
    raise RuntimeError("TEACHER_EMAILS environment variable must be set")

EXPECTED_HD = os.environ.get("GOOGLE_HD", "")


def get_redirect_uri() -> str:
    return os.environ.get("REDIRECT_URI", "http://localhost:8080/callback")


def get_client_config() -> dict[str, Any]:
    raw = os.environ.get("GOOGLE_CLIENT_SECRET")
    if raw:
        return json.loads(raw)
    raise KeyError("GOOGLE_CLIENT_SECRET environment variable not set")


def get_auth_url(redirect_uri: str | None = None) -> tuple[str, str, str | None]:
    client_config = get_client_config()
    flow = Flow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=redirect_uri or get_redirect_uri()
    )
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    return auth_url, state, flow.code_verifier


def exchange_code(
    code: str, code_verifier: str | None, redirect_uri: str | None = None
) -> dict[str, Any]:
    client_config = get_client_config()
    flow = Flow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=redirect_uri or get_redirect_uri()
    )
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    user_info_service = build("oauth2", "v2", credentials=flow.credentials)
    user_info: dict[str, Any] = user_info_service.userinfo().get().execute()
    hd = user_info.get("hd", "")
    if EXPECTED_HD and hd != EXPECTED_HD:
        raise ValueError(
            f"Google Workspace domain mismatch: expected '{EXPECTED_HD}', got '{hd}'"
        )
    return user_info


def is_teacher(email: str) -> bool:
    return email in TEACHER_EMAILS
