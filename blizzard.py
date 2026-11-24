"""Shared helpers: Blizzard API token, item name/ID lookups and money formatting."""

import base64
import json
import os
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
IDS_FILE = HERE / "data" / "item_ids.json"  # name -> [ids], gitignored cache
API = "https://eu.api.blizzard.com/data/wow"
NS = {"namespace": "static-forever-eu", "locale": "en_GB"}


_token = None


def token():
    """App-only (client_credentials) Blizzard token, fetched once per run.
    Credentials from BLIZZARD_CLIENT_ID/SECRET (GitHub Actions), else config.toml."""
    global _token
    if _token is None:
        if os.environ.get("BLIZZARD_CLIENT_ID"):
            c = {"client_id": os.environ["BLIZZARD_CLIENT_ID"], "client_secret": os.environ["BLIZZARD_CLIENT_SECRET"]}
        else:
            c = tomllib.loads((HERE / "config.toml").read_text())["battlenet"]
        basic = base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
        req = urllib.request.Request("https://oauth.battle.net/token", b"grant_type=client_credentials",
                                     {"Authorization": "Basic " + basic})
        _token = json.load(urllib.request.urlopen(req))["access_token"]
    return _token


def _get(path, **params):
    url = f"{API}/{path}?" + urllib.parse.urlencode({**NS, **params})
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer " + token()})))


_ids = json.loads(IDS_FILE.read_text()) if IDS_FILE.exists() else {}


def item_ids(name):
    """Every Forever item ID with exactly this name (some names exist twice)."""
    if name not in _ids:
        results = _get("search/item", **{"name.en_GB": name, "_pageSize": 50})["results"]
        _ids[name] = [r["data"]["id"] for r in results if r["data"]["name"].get("en_GB", "").lower() == name.lower()]
        IDS_FILE.write_text(json.dumps(_ids))
    return _ids[name]


def item_name(item_id):
    for name, ids in _ids.items():
        if item_id in ids:
            return name
    try:
        name = _get(f"item/{item_id}")["name"]
    except urllib.error.HTTPError:  # some gear IDs 404 in the Forever namespace
        return f"item {item_id}"
    _ids.setdefault(name, []).append(item_id)
    IDS_FILE.write_text(json.dumps(_ids))
    return name


def money(copper):
    copper = round(copper)
    sign = "-" if copper < 0 else ""
    g, rest = divmod(abs(copper), 10000)
    s, c = divmod(rest, 100)
    return sign + (f"{g}g {s}s" if g else f"{s}s {c}c" if s else f"{c}c")
