import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fleet_analysis_new as core

core.CONFIG_FILE = str(ROOT / "config.json")

_SESSION_COOKIE_NAME = "session_token"
_SESSION_TTL_SECONDS = 12 * 60 * 60


_init_done = False


def _ensure_init():
    global _init_done
    if _init_done:
        return

    if core.MYSQL_AVAILABLE:
        try:
            core.setup_database_tables()
        except Exception as exc:
            logging.warning("DB setup skipped: %s", exc)

    _init_done = True


def _secret_key() -> str:
    return os.environ.get("SESSION_SECRET", "change-me-in-vercel")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("utf-8"))


def _sign(payload_raw: bytes) -> str:
    return hmac.new(_secret_key().encode("utf-8"), payload_raw, hashlib.sha256).hexdigest()


def _create_session_token(client_id: str) -> str:
    payload = {
        "sub": client_id,
        "exp": int(time.time()) + _SESSION_TTL_SECONDS,
    }
    payload_raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return f"{_b64url_encode(payload_raw)}.{_sign(payload_raw)}"


def _verify_session_token(token: str) -> bool:
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return False
        payload_b64, sig = parts
        payload_raw = _b64url_decode(payload_b64)
        expected_sig = _sign(payload_raw)
        if not hmac.compare_digest(sig, expected_sig):
            return False
        payload = json.loads(payload_raw.decode("utf-8"))
        return int(payload.get("exp", 0)) > int(time.time())
    except Exception:
        return False


def _get_cookie_value(environ, name: str) -> str:
    cookie_header = environ.get("HTTP_COOKIE", "")
    if not cookie_header:
        return ""

    for entry in cookie_header.split(";"):
        if "=" not in entry:
            continue
        key, val = entry.strip().split("=", 1)
        if key == name:
            return val
    return ""


def _is_authenticated(environ) -> bool:
    token = _get_cookie_value(environ, _SESSION_COOKIE_NAME)
    if not token:
        return False
    return _verify_session_token(token)


def _read_json_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0

    body = environ["wsgi.input"].read(length) if length > 0 else b""
    if not body:
        return {}

    return json.loads(body.decode("utf-8"))


def _json_response(start_response, status: str, payload, extra_headers=None):
    body = json.dumps(payload).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Cache-Control", "no-store"),
        ("Content-Length", str(len(body))),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    start_response(status, headers)
    return [body]


def _html_response(start_response, html: str):
    body = html.encode("utf-8")
    headers = [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Cache-Control", "no-store"),
        ("Content-Length", str(len(body))),
    ]
    start_response("200 OK", headers)
    return [body]


def _load_config():
    return core.load_runtime_config()


def app(environ, start_response):
    _ensure_init()

    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")

    if path == "/" and method == "GET":
        return _html_response(start_response, core.HTML_TEMPLATE)

    if path == "/favicon.ico":
        start_response("204 No Content", [])
        return [b""]

    if path == "/api/check-session" and method == "GET":
        return _json_response(start_response, "200 OK", {"logged_in": _is_authenticated(environ)})

    if path == "/api/login" and method == "POST":
        try:
            payload = _read_json_body(environ)
            client_id = payload.get("client_id", "").strip()
            client_secret = payload.get("client_secret", "").strip()

            if not client_id or not client_secret:
                return _json_response(
                    start_response,
                    "200 OK",
                    {"success": False, "message": "Enter Client ID and Secret"},
                )

            config = _load_config()
            auth_config = config.get("auth", {})
            url = f"{auth_config['base_url'].rstrip('/')}/{auth_config['endpoint'].lstrip('/')}"
            resp = requests.post(
                url,
                json={"clientId": client_id, "clientSecret": client_secret},
                timeout=10,
            )

            if resp.status_code != 200:
                msg = f"Auth API returned {resp.status_code}"
                try:
                    msg = resp.json().get("message", msg)
                except Exception:
                    pass
                return _json_response(start_response, "200 OK", {"success": False, "message": msg})

            token_data = resp.json().get("data", {})
            access_token = token_data.get("accessToken")
            if not access_token:
                return _json_response(
                    start_response,
                    "200 OK",
                    {"success": False, "message": "No token in response"},
                )

            now = int(time.time())
            core.AUTH_TOKEN_CACHE["token"] = access_token
            core.AUTH_TOKEN_CACHE["expires_at"] = now + core.TOKEN_EXPIRY_SECONDS

            session_token = _create_session_token(client_id)
            return _json_response(
                start_response,
                "200 OK",
                {"success": True},
                extra_headers=[
                    (
                        "Set-Cookie",
                        f"{_SESSION_COOKIE_NAME}={session_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={_SESSION_TTL_SECONDS}",
                    )
                ],
            )
        except Exception as exc:
            logging.exception("Login error")
            return _json_response(
                start_response,
                "200 OK",
                {"success": False, "message": "Server error: " + str(exc)[:60]},
            )

    if path == "/api/logout" and method == "POST":
        return _json_response(
            start_response,
            "200 OK",
            {"success": True},
            extra_headers=[
                (
                    "Set-Cookie",
                    f"{_SESSION_COOKIE_NAME}=deleted; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
                )
            ],
        )

    protected_routes = {
        ("GET", "/api/da/vehicles/filters"),
        ("GET", "/api/vld/vehicles/filters"),
        ("POST", "/api/da/fetch"),
        ("POST", "/api/vld/fetch"),
        ("POST", "/api/registry/sync"),
    }

    if (method, path) in protected_routes and not _is_authenticated(environ):
        return _json_response(start_response, "403 Forbidden", {"error": "Unauthorized"})

    if path == "/api/da/vehicles/filters" and method == "GET":
        data = core.get_vehicle_filters_from_db(vld=False)
        return _json_response(start_response, "200 OK", data)

    if path == "/api/vld/vehicles/filters" and method == "GET":
        data = core.get_vehicle_filters_from_db(vld=True)
        return _json_response(start_response, "200 OK", data)

    if path == "/api/da/fetch" and method == "POST":
        try:
            params = _read_json_body(environ)
            core.fetch_and_process_data(params)
            payload = {
                "total_eligible": core.DATA_STORE["total_eligible"],
                "success": core.DATA_STORE["success"],
                "failed": core.DATA_STORE["failed"],
            }
            return _json_response(start_response, "200 OK", payload)
        except Exception as exc:
            return _json_response(start_response, "500 Internal Server Error", {"error": str(exc)})

    if path == "/api/vld/fetch" and method == "POST":
        try:
            params = _read_json_body(environ)
            core.fetch_and_process_data_vld(params)
            payload = {
                "total_eligible": core.VLD_DATA_STORE["total_eligible"],
                "success": core.VLD_DATA_STORE["success"],
                "failed": core.VLD_DATA_STORE["failed"],
            }
            return _json_response(start_response, "200 OK", payload)
        except Exception as exc:
            return _json_response(start_response, "500 Internal Server Error", {"error": str(exc)})

    if path == "/api/registry/sync" and method == "POST":
        try:
            core.sync_registry_to_db()
            return _json_response(start_response, "200 OK", {"status": "done"})
        except Exception as exc:
            return _json_response(start_response, "500 Internal Server Error", {"error": str(exc)})

    return _json_response(start_response, "404 Not Found", {"error": "Not Found"})
