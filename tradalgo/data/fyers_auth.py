import hashlib
from datetime import date, timedelta

import requests
from fyers_apiv3 import fyersModel

API = "https://api-t1.fyers.in/api/v3"
REFRESH_TOKEN_VALID_DAYS = 15


class AuthError(RuntimeError):
    pass


def app_id_hash(app_id: str, secret: str) -> str:
    return hashlib.sha256(f"{app_id}:{secret}".encode()).hexdigest()


def require(store, name: str) -> str:
    value = store.get(name)
    if not value:
        raise AuthError(f"{name} missing from keychain; set it with keyring.set_password('tradalgo', '{name}', ...)")
    return value


def auth_url(app_id: str, secret: str, redirect_uri: str) -> str:
    return fyersModel.SessionModel(
        client_id=app_id, secret_key=secret, redirect_uri=redirect_uri,
        response_type="code", state="tradalgo", grant_type="authorization_code",
    ).generate_authcode()


def _post(post, path: str, payload: dict) -> dict:
    resp = post(f"{API}{path}", json=payload, timeout=15).json()
    if resp.get("s") != "ok":
        # never interpolate the body: /validate-authcode responses carry access_token / refresh_token
        raise AuthError(f"FYERS {path} failed: "
                        f"{resp.get('message', f'unexpected response (keys: {sorted(resp)})')}")
    return resp


def login_with_auth_code(store, auth_code: str, today: date, post=requests.post) -> None:
    """One-time browser flow: exchange the redirect auth_code for access + refresh tokens and store them."""
    resp = _post(post, "/validate-authcode", {
        "grant_type": "authorization_code",
        "appIdHash": app_id_hash(require(store, "FYERS_APP_ID"), require(store, "FYERS_SECRET_KEY")),
        "code": auth_code,
    })
    store.set("FYERS_ACCESS_TOKEN", resp["access_token"])
    store.set("FYERS_ACCESS_TOKEN_DATE", today.isoformat())
    store.set("FYERS_REFRESH_TOKEN", resp["refresh_token"])
    store.set("FYERS_REFRESH_TOKEN_ISSUED", today.isoformat())


def refresh_token_expiry(store) -> date | None:
    issued = store.get("FYERS_REFRESH_TOKEN_ISSUED")
    return date.fromisoformat(issued) + timedelta(days=REFRESH_TOKEN_VALID_DAYS) if issued else None


def get_access_token(store, today: date, post=requests.post) -> str:
    """Today's access token, refreshed via refresh token + PIN (no browser) when stale."""
    if store.get("FYERS_ACCESS_TOKEN_DATE") == today.isoformat():
        return require(store, "FYERS_ACCESS_TOKEN")
    expiry = refresh_token_expiry(store)
    if expiry is None or today >= expiry:
        raise AuthError("FYERS refresh token missing or expired; run `tradalgo login`")
    resp = _post(post, "/validate-refresh-token", {
        "grant_type": "refresh_token",
        "appIdHash": app_id_hash(require(store, "FYERS_APP_ID"), require(store, "FYERS_SECRET_KEY")),
        "refresh_token": require(store, "FYERS_REFRESH_TOKEN"),
        "pin": require(store, "FYERS_PIN"),
    })
    store.set("FYERS_ACCESS_TOKEN", resp["access_token"])
    store.set("FYERS_ACCESS_TOKEN_DATE", today.isoformat())
    return resp["access_token"]
