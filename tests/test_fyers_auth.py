import hashlib
from datetime import date

import pytest

from tradalgo.data import fyers_auth
from tradalgo.data.fyers_auth import AuthError, get_access_token, login_with_auth_code


class MemoryStore(dict):
    def set(self, name, value):
        self[name] = value


class FakePost:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, json, timeout):
        self.calls.append((url, json))
        return type("Resp", (), {"json": lambda _self: self.response})()


def creds(**extra):
    return MemoryStore(FYERS_APP_ID="APP-100", FYERS_SECRET_KEY="SECRET", FYERS_PIN="1234", **extra)


HASH = hashlib.sha256(b"APP-100:SECRET").hexdigest()


def test_login_exchanges_auth_code_and_stores_tokens():
    store = creds()
    post = FakePost({"s": "ok", "access_token": "acc", "refresh_token": "ref"})
    login_with_auth_code(store, "CODE", date(2026, 9, 13), post=post)
    assert post.calls == [(f"{fyers_auth.API}/validate-authcode",
                           {"grant_type": "authorization_code", "appIdHash": HASH, "code": "CODE"})]
    assert store["FYERS_REFRESH_TOKEN"] == "ref"
    assert store["FYERS_ACCESS_TOKEN_DATE"] == "2026-09-13"


def test_same_day_access_token_reused_without_network():
    store = creds(FYERS_ACCESS_TOKEN="acc", FYERS_ACCESS_TOKEN_DATE="2026-09-14")
    post = FakePost({})
    assert get_access_token(store, date(2026, 9, 14), post=post) == "acc"
    assert post.calls == []


def test_stale_access_token_refreshed_with_pin():
    store = creds(FYERS_ACCESS_TOKEN="old", FYERS_ACCESS_TOKEN_DATE="2026-09-11",
                  FYERS_REFRESH_TOKEN="ref", FYERS_REFRESH_TOKEN_ISSUED="2026-09-01")
    post = FakePost({"s": "ok", "access_token": "new"})
    assert get_access_token(store, date(2026, 9, 15), post=post) == "new"
    assert post.calls == [(f"{fyers_auth.API}/validate-refresh-token", {
        "grant_type": "refresh_token", "appIdHash": HASH, "refresh_token": "ref", "pin": "1234"})]
    assert store["FYERS_ACCESS_TOKEN_DATE"] == "2026-09-15"


def test_expired_refresh_token_requires_login():
    store = creds(FYERS_REFRESH_TOKEN="ref", FYERS_REFRESH_TOKEN_ISSUED="2026-09-01")
    with pytest.raises(AuthError, match="tradalgo login"):
        get_access_token(store, date(2026, 9, 16), post=FakePost({}))


def test_api_rejection_raises_auth_error():
    store = creds(FYERS_REFRESH_TOKEN="ref", FYERS_REFRESH_TOKEN_ISSUED="2026-09-10")
    with pytest.raises(AuthError, match="invalid pin"):
        get_access_token(store, date(2026, 9, 11), post=FakePost({"s": "error", "message": "invalid pin"}))


def test_missing_secret_names_the_key():
    with pytest.raises(AuthError, match="FYERS_SECRET_KEY"):
        login_with_auth_code(MemoryStore(FYERS_APP_ID="APP-100"), "CODE", date(2026, 9, 13), post=FakePost({}))
