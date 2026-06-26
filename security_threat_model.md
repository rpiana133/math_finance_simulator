# Security Threat Model: Math Finance Simulator

This document outlines the threat model for the Math Finance Simulator using the STRIDE methodology. It identifies potential threats and documents the mitigations implemented in the application architecture.

## Architecture Overview
- **Frontend/Backend**: Python-based web server using NiceGUI (which wraps FastAPI, Vue.js, and Starlette).
- **Authentication**: Google OAuth 2.0 with domain-restricted Workspace hd validation.
- **Session Storage**: In-memory dict keyed by opaque `secrets.token_urlsafe(32)` tokens; only the token survives in `app.storage.user` (on-disk JSON). Sessions lost on instance recycle (forces re-auth).
- **Database**: Google Cloud Storage (JSON blobs) with HMAC-SHA-256 derived blob keys.
- **Deployment**: Docker container (Google Cloud Run).

---

## STRIDE Threat Analysis

### 1. Spoofing (Authentication & Identity)
**Threat:** An attacker attempts to forge their identity or spoof another student's/teacher's profile to execute trades or view unauthorized portfolios.

**Mitigations:**
- **OAuth 2.0:** All sessions are authenticated strictly via Google Workspace. No custom passwords are used.
- **Domain Validation:** The `GOOGLE_HD` env var restricts OAuth logins to a specific Workspace domain (`stjohnsguam.com`). Logins from non-whitelisted domains are rejected in `exchange_code()`.
- **Session Timeout:** Sessions idle for >30 minutes are automatically invalidated via `_check_session_timeout()` on page load.
- **State Validation:** The OAuth flow enforces an anti-forgery `state` parameter to prevent CSRF login attacks.
- **In-Memory Sessions:** Session data is stored in a process-local `_session_store` dict referenced by opaque tokens; no session data (email, name, IP) survives in the on-disk NiceGUI storage file.

### 2. Tampering (Data Integrity)
**Threat:** An attacker manipulates incoming requests to modify their cash balance, shares owned, or alert prices maliciously.

**Mitigations:**
- **Server-Side Validation:** Client-side bounds (e.g., `<input min="0.001">`) are insufficient. The server re-validates all trades (`_validate_trade_inputs` → `_execute_trade`) to ensure shares > 0, requested action is valid (`Buy`/`Sell`), and the user possesses sufficient cash or shares before processing.
- **Price Drift Protection:** `_execute_trade` fetches a live price and rejects trades where the user-submitted price deviates >2% from the live price, preventing stale/manipulated pricing.
- **Data Lock:** A `threading.Lock` protects concurrent read/writes to user profile blobs, preventing race conditions (e.g., executing two trades simultaneously to bypass cash limits).
- **TOCTOU Race Prevention:** A dedicated `_token_lock = Lock()` wraps GCS token cache check + fetch in `_gcs_token()` to prevent time-of-check/time-of-use race conditions.
- **Admin Variable Shadowing Fix:** `_do_remove()` uses `target_email` (not bare `email`) to avoid shadowing the outer teacher email variable.

### 3. Repudiation (Non-Repudiability)
**Threat:** A user performs a malicious action (e.g., exploiting a bug or deleting alerts) and denies doing so, or an admin cannot trace the source of a breach.

**Mitigations:**
- **Structured Audit Logging:** Every critical action (`LOGIN`, `BUY`, `SELL`, `ALERT_CREATE`, `ALERT_DELETE`, `ADMIN_REMOVE_STUDENT`, `UNAUTHORIZED_ADMIN_ATTEMPT`) emits a structured JSON log containing the `event`, timestamp, `user` email, `ip` address, and specific action `details`.
- **Unauthorized Access Logging:** Non-teacher attempts to invoke admin functions are explicitly logged as `UNAUTHORIZED_ADMIN_ATTEMPT`.

### 4. Information Disclosure (Privacy & Leaks)
**Threat:** An attacker accesses sensitive environment variables, gains unauthorized access to GCS blobs, exploits directory traversal, or exfiltrates session data from on-disk storage.

**Mitigations:**
- **HMAC-SHA-256 Blob Keys:** `_safe_email_key()` derives GCS blob paths using `hmac.new(BLOB_KEY_SECRET, email.encode(), hashlib.sha256).hexdigest()`, preventing directory traversal and masking PII in storage bucket filenames. Falls back to SHA-256 if `BLOB_KEY_SECRET` is unset (migration-safe).
- **In-Memory Session Store:** The `_session_store` dict is process-local and keyed by opaque `secrets.token_urlsafe(32)` tokens. Only the token survives in `app.storage.user` (disk-backed); email, name, IP, and `last_activity` are stripped from disk storage.
- **Environment Secrets:** All sensitive keys (OAuth client secrets, Finnhub API keys, storage credentials) are passed exclusively via environment variables. No secrets are baked into the repository or Docker image.
- **`.env.yaml` Untracked:** The env-var template is added to `.gitignore` and `git rm --cached` removes it from history.
- **`TRUSTED_PROXIES` Hardening:** `filter(None, ...)` avoids empty-string set entries; a warning is logged when unset.

### 5. Denial of Service (Availability)
**Threat:** An attacker spams the OAuth callback or heavy computation endpoints to exhaust server resources.

**Mitigations:**
- **Rate Limiting:** The `/callback` endpoint is protected by an in-memory sliding window rate limiter (`TTLCache`; max 5 requests per minute per IP).
- **Thread Pooling:** Blocking I/O operations (yfinance calls) are offloaded to a shared `ThreadPoolExecutor(max_workers=4)` instead of ad-hoc fire-and-forget executors.
- **CI/CD Vulnerability Scanning:** The Dockerfile runs `pip-audit` during build; 6 known NiceGUI 3.6.1 CVEs are explicitly ignored; any unexpected CVE causes a build failure.

### 6. Elevation of Privilege (Authorization & RCE)
**Threat:** An attacker exploits an XSS vulnerability to hijack a teacher's session and perform admin actions, or achieves Remote Code Execution (RCE) on the container.

**Mitigations:**
- **XSS Prevention:** User-controlled display names, emails, and ticker symbols are explicitly escaped using `html.escape()` before rendering in raw HTML blocks (`ui.html`). This applies to all 9 `ui.html(sanitize=False)` calls in `main.py`, including alert banners in `_check_alerts()`.
- **Security Headers:** FastAPI middleware enforces `nosniff`, `DENY` frame options, HSTS, and a Content-Security-Policy (CSP). Note: The CSP currently requires `unsafe-inline` and `unsafe-eval` due to NiceGUI/Vue.js requirements.
- **Container Hardening:** The Docker image creates and drops privileges to a non-root `appuser`, severely limiting the blast radius of any potential RCE vulnerability.

---

## Known Residual Risks & Recommendations
- **CSP Relaxations:** The use of `unsafe-inline` and `unsafe-eval` in the Content-Security-Policy is a required trade-off for NiceGUI 3.6.1, which does not natively support nonce-based CSP. Re-evaluate when NiceGUI merges native nonce support.
- **Dependency Vulnerabilities:** NiceGUI 3.6.1 is the latest on PyPI but carries 6 known CVEs with no upgrade path. These are explicitly ignored in `pip-audit` (`--ignore-vuln`). Unexpected CVEs cause a build failure.
- **Negative Security Tests:** A dedicated `tests/test_security.py` suite (25 tests) covers session store integrity, rate-limiter sliding window, OAuth state mismatch, balance invariance, teacher access control, and HMAC key store behavior.
- **Ephemeral Sessions:** In-memory `_session_store` is lost on Cloud Run instance recycle (no `min-instances`). This forces re-authentication on cold start, which is acceptable for a classroom simulator.

## Deployment Configuration

### Cloud Run Settings
- **Session Affinity:** Must be enabled. In-memory `_session_store` and NiceGUI WebSockets require requests to stick to the same instance.
- **Request Timeout:** Increase to >=600s to prevent Google Front End from terminating idle WebSocket connections.
- **Port:** `8080` (injected via `PORT` env var, read dynamically in `main.py`).

### Environment Variables
| Variable | Source | Purpose |
|----------|--------|---------|
| `STORAGE_SECRET` | Secret Manager | Encrypts NiceGUI browser session cookie |
| `GOOGLE_CLIENT_SECRET` | Secret Manager | Full OAuth 2.0 client JSON |
| `GCS_SERVICE_ACCOUNT` | Secret Manager | JSON key for GCS bucket access |
| `BLOB_KEY_SECRET` | Secret Manager | HMAC key for GCS blob path derivation |
| `FINNHUB_API_KEY` | Plain env | Live market data (Finnhub) API key |
| `TEACHER_EMAILS` | Plain env | Comma-separated list of teacher emails for admin access |
| `GOOGLE_HD` | Plain env | Google Workspace domain to restrict logins (e.g., `stjohnsguam.com`) |
| `REDIRECT_URI` | Plain env | (Optional) overrides auto-detected OAuth callback URL |

No `min-instances` is configured due to cost sensitivity.
