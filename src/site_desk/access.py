"""Account credentials and bounded HTTP calls to fixed service origins."""

import os
import re
from urllib.parse import urlsplit

import httpx
import keyring
from keyring.errors import NoKeyringError

SERVICES = {
    "webmaster": "SITE_DESK_WEBMASTER_TOKEN",
    "metrica": "SITE_DESK_METRICA_TOKEN",
    "geocoder": "SITE_DESK_GEOCODER_KEY",
    "router": "SITE_DESK_ROUTER_KEY",
    "indexnow": "SITE_DESK_INDEXNOW_KEY",
}
WM = "https://api.webmaster.yandex.net/v4/user"
MET = "https://api-metrika.yandex.net/management/v1"


def credential(service, required=True):
    value = os.environ.get(SERVICES[service])
    if not value:
        try:
            value = keyring.get_password("grebennikov-site-desk", service)
        except NoKeyringError:
            pass
    if required and not value:
        raise ValueError(f"Connect {service} locally: ya-webmaster connect {service}")
    return value


def request(method, url, *, token=None, params=None, body=None, allow_text=False):
    headers = {
        "User-Agent": "Ya-Webmaster/0.1 (+https://github.com/grebennikovxyz/ya-webmaster-metrica-plugin)"
    }
    if token:
        headers["Authorization"] = "OAuth " + token
    try:
        response = httpx.request(
            method,
            url,
            params=params,
            json=body,
            headers=headers,
            timeout=25,
            follow_redirects=False,
        )
    except httpx.RequestError:
        raise ValueError(
            f"{urlsplit(url).hostname}: connection interrupted. Check remote state before retrying a write."
        ) from None
    if not response.is_success:
        code = ""
        try:
            code = str(response.json().get("error_code", ""))
        except (ValueError, AttributeError):
            pass
        raise ValueError(
            f"{urlsplit(url).hostname}: HTTP {response.status_code} {code if re.fullmatch('[A-Z_]{1,64}', code) else ''}".strip()
        )
    if allow_text:
        return {"http_status": response.status_code}
    return response.json() if response.content else {}


def met(method, path, *, body=None, params=None):
    return request(
        method, MET + path, token=credential("metrica"), params=params, body=body
    )


def wm(method, path="", *, body=None, params=None):
    token = credential("webmaster")
    uid = int(request("GET", WM, token=token)["user_id"])
    return request(
        method, f"{WM}/{uid}/hosts{path}", token=token, params=params, body=body
    )


def website(value):
    if not isinstance(value, str) or any(ord(c) < 33 or c == "\\" for c in value):
        raise ValueError("Expected a public HTTP(S) URL")
    u = urlsplit(value)
    if (
        u.scheme not in ("http", "https")
        or not u.hostname
        or u.username is not None
        or u.password is not None
        or u.port not in (None, 80 if u.scheme == "http" else 443)
    ):
        raise ValueError(
            "Use a public HTTP(S) URL with a standard port and no credentials"
        )
    return u


def domain(value):
    return website(value).hostname.encode("idna").decode().lower().rstrip(".")
