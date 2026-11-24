"""Hourly pull of the WoW Forever (EU) auction house from the Blizzard API into data/ah.sqlite,
plus a report for re-ranking the snipe list. Runs hourly on GitHub Actions
(.github/workflows/wow-ah-pull.yml), which pushes data/ah_summary.json to the ah-data branch.

  python3 ah_pull.py               store the latest snapshot (skips one already stored)
  python3 ah_pull.py report [cap]  snipe-list check and the best items not on it (cap in copper, default 1g)

Blizzard has no sales data, so sales are estimated from listings that vanish between hourly
pulls while they still had 2h+ left (bought or cancelled, not expired). Treat it as a guide.
"""

import json
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

import blizzard

RULESET, HOUSE = 2, 111  # Normal, Alliance: matched exactly against TSM's Normal-Alliance data 2026-11-20
DB = blizzard.HERE / "data" / "ah.sqlite"
SUMMARY = blizzard.HERE / "data" / "ah_summary.json"
KEEP_DAYS = 14
STILL_LIVE = {"LONG", "VERY_LONG"}
MAX_GAP = 90 * 60  # longer gap between pulls (PC off) and LONG listings may have expired, so no sales estimate


def fetch(path, since):
    """(Last-Modified epoch, auctions) or None if Blizzard says nothing changed."""
    url = f"{blizzard.API}/ruleset/{RULESET}/auctions/{HOUSE}{path}?namespace=dynamic-forever-eu"
    headers = {"Authorization": "Bearer " + blizzard.token()}
    if since:
        headers["If-Modified-Since"] = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(since))
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None
        raise
    body = json.load(r)
    if "auctions" not in body:  # fail loudly if Blizzard changes the shape
        raise RuntimeError(f"no 'auctions' in {path or 'items'} response, keys: {list(body)}")
    return int(parsedate_to_datetime(r.headers["Last-Modified"]).timestamp()), body["auctions"]


def connect():
    db = sqlite3.connect(DB)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER);
        CREATE TABLE IF NOT EXISTS snap (ts INTEGER, item INTEGER, min INTEGER, median INTEGER, qty INTEGER, n INTEGER,
                                         PRIMARY KEY (ts, item));
        CREATE TABLE IF NOT EXISTS sold (ts INTEGER, item INTEGER, qty INTEGER, value INTEGER, PRIMARY KEY (ts, item));
        CREATE TABLE IF NOT EXISTS seen (id INTEGER PRIMARY KEY, item INTEGER, qty INTEGER, unit INTEGER, time_left TEXT);
        CREATE TABLE IF NOT EXISTS vendor (item INTEGER PRIMARY KEY, price INTEGER, commodity INTEGER);
        CREATE TABLE IF NOT EXISTS vdeal (ts INTEGER, item INTEGER, listings INTEGER, lasted INTEGER, lasted_profit INTEGER,
                                          PRIMARY KEY (ts, item));
    """)
    try:  # older databases: seen.old marks a listing already counted as a lasting vendor deal
        db.execute("ALTER TABLE seen ADD COLUMN old INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    return db


def vendor_prices(db, items, commodity_items):
    """Vendor sell price per item, from the Blizzard item API once, then from the vendor table."""
    known = dict(db.execute("SELECT item, price FROM vendor"))
    missing = [i for i in items if i not in known]
    if not missing:
        return known
    blizzard.token()  # fetch the token once, before the threads share it

    def look(item):
        for attempt in range(4):
            try:
                return item, blizzard._get(f"item/{item}").get("sell_price", 0)
            except urllib.error.HTTPError as e:
                if e.code == 404:  # some IDs are missing from the Forever namespace
                    return item, 0
                if e.code != 429:
                    break
                time.sleep(1 + attempt)  # Blizzard allows 100 requests a second
            except OSError:
                break
        return item, None  # network trouble: leave it for the next run

    with ThreadPoolExecutor(8) as pool:
        found = [(i, p) for i, p in pool.map(look, missing) if p is not None]
    db.executemany("INSERT OR REPLACE INTO vendor VALUES (?,?,?)", [(i, p, int(i in commodity_items)) for i, p in found])
    known.update(found)
    print(f"looked up {len(found)} of {len(missing)} new vendor prices")
    return known


def pull():
    db = connect()
    last = (db.execute("SELECT value FROM meta WHERE key='last_modified'").fetchone() or [0])[0]
    items, commodities = fetch("", last), fetch("/commodities", last)
    if items is None or commodities is None or max(items[0], commodities[0]) <= last:
        print("no new snapshot since", time.strftime("%H:%M", time.localtime(last)))
        return
    ts = max(items[0], commodities[0])
    rows = [(a["id"], a["item"]["id"], a["quantity"], a["buyout"] // a["quantity"], a["time_left"])
            for a in items[1] if a.get("buyout")]  # bid-only listings have no buyout
    rows += [(a["id"], a["item"]["id"], a["quantity"], a["unit_price"], a["time_left"]) for a in commodities[1]]

    by_item = {}
    for _, item, qty, unit, _ in rows:
        by_item.setdefault(item, []).append((unit, qty))
    summary = []
    for item, listings in by_item.items():
        listings.sort()
        total, half, run = sum(q for _, q in listings), sum(q for _, q in listings) / 2, 0
        for unit, qty in listings:  # quantity-weighted median
            run += qty
            if run >= half:
                break
        summary.append((ts, item, listings[0][0], unit, total, len(listings)))
    db.executemany("INSERT OR REPLACE INTO snap VALUES (?,?,?,?,?,?)", summary)
    vendor = vendor_prices(db, by_item, {a["item"]["id"] for a in commodities[1]})

    # Listings under vendor price, and which of them were already there an hour ago: a deal
    # that lasts an hour is on an item nobody is camping.
    fresh = last and ts - last <= MAX_GAP
    before = {aid: old for aid, item, unit, old in db.execute("SELECT id, item, unit, old FROM seen")
              if unit < (vendor.get(item) or 0)} if fresh else {}
    deals = {}  # item -> [listings, lasted, profit from the lasting ones]
    for aid, item, qty, unit, _ in rows:
        v = vendor.get(item) or 0
        if unit < v:
            d = deals.setdefault(item, [0, 0, 0])
            d[0] += 1
            if aid in before and not before[aid]:  # count each listing once, the hour it first lasts
                d[1] += 1
                d[2] += (v - unit) * qty
    db.executemany("INSERT OR REPLACE INTO vdeal VALUES (?,?,?,?,?)", [(ts, i, *d) for i, d in deals.items()])

    if fresh:
        now = {r[0]: r[2] for r in rows}
        gone = {}  # item -> [qty, copper]
        for aid, item, qty, unit, left in db.execute("SELECT id, item, qty, unit, time_left FROM seen"):
            if left in STILL_LIVE and now.get(aid, 0) < qty:  # vanished, or a commodity stack partly bought
                g = gone.setdefault(item, [0, 0])
                g[0] += qty - now.get(aid, 0)
                g[1] += (qty - now.get(aid, 0)) * unit
        db.executemany("INSERT OR REPLACE INTO sold VALUES (?,?,?,?)", [(ts, i, q, v) for i, (q, v) in gone.items()])
    db.execute("DELETE FROM seen")
    db.executemany("INSERT INTO seen VALUES (?,?,?,?,?,?)", [(*r, int(r[0] in before)) for r in rows])
    db.execute("INSERT OR REPLACE INTO meta VALUES ('last_modified', ?)", (ts,))
    cutoff = ts - KEEP_DAYS * 86400
    db.execute("DELETE FROM snap WHERE ts < ?", (cutoff,))
    db.execute("DELETE FROM sold WHERE ts < ?", (cutoff,))
    db.execute("DELETE FROM vdeal WHERE ts < ?", (cutoff,))
    db.commit()
    summarise(db)
    print(time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)), f"{len(rows)} listings, {len(summary)} items stored")


def summarise(db):
    """Per-item figures for the last 7 days, written to SUMMARY: the small file the report
    (and later an addon) reads, so the database itself can stay on GitHub."""
    week = time.time() - 7 * 86400
    snaps = db.execute("SELECT COUNT(DISTINCT ts) FROM snap WHERE ts >= ?", (week,)).fetchone()[0]
    sale_hours = db.execute("SELECT COUNT(DISTINCT ts) FROM sold WHERE ts >= ?", (week,)).fetchone()[0]
    latest = db.execute("SELECT MAX(ts) FROM snap").fetchone()[0]
    items = {}  # id -> [listed (median of hourly medians), sold at, now (lowest), sold per day]
    for item, meds in db.execute("SELECT item, GROUP_CONCAT(median) FROM snap WHERE ts >= ? GROUP BY item", (week,)):
        meds = sorted(map(int, meds.split(",")))
        items[item] = [meds[len(meds) // 2], None, None, 0]
    for item, low in db.execute("SELECT item, min FROM snap WHERE ts = ?", (latest,)):
        items[item][2] = low
    for item, q, v in db.execute("SELECT item, SUM(qty), SUM(value) FROM sold WHERE ts >= ? GROUP BY item", (week,)):
        if item in items:
            items[item][1], items[item][3] = round(v / q), round(q * 24 / sale_hours, 1)
    vendor = {}  # id -> [vendor price, commodity 0/1, listings under vendor, lasted an hour, profit from lasting]
    for item, price, comm, n, lasted, profit in db.execute(
            "SELECT d.item, v.price, v.commodity, SUM(listings), SUM(lasted), SUM(lasted_profit) FROM vdeal d "
            "JOIN vendor v ON v.item = d.item WHERE ts >= ? GROUP BY d.item", (week,)):
        vendor[item] = [price, comm, n, lasted, profit]
    SUMMARY.write_text(json.dumps({"updated": latest, "snapshots": snaps, "sale_hours": sale_hours, "items": items,
                                   "vendor": vendor},
                                  separators=(",", ":")))


def load_summary():
    """The newer of the GitHub Action's summary (ah-data branch) and the local timer's file."""
    found = []
    try:
        subprocess.run(["git", "-C", blizzard.HERE, "fetch", "-q", "origin", "ah-data"], check=True, capture_output=True)
        found.append((subprocess.run(["git", "-C", blizzard.HERE, "show", "origin/ah-data:ah_summary.json"],
                                     check=True, capture_output=True, text=True).stdout, "GitHub (ah-data branch)"))
    except subprocess.CalledProcessError:
        pass
    if SUMMARY.exists():
        found.append((SUMMARY.read_text(), "local"))
    if not found:
        return None, None
    data, source = max(((json.loads(t), src) for t, src in found), key=lambda f: (f[0]["updated"], f[0]["snapshots"]))
    data["items"] = {int(k): v for k, v in data["items"].items()}
    return data, source


def report(cap):
    data, source = load_summary()
    if not data:
        print("no summary yet, run: python3 ah_pull.py")
        return
    items = data["items"]
    print(f"{source}, snapshot {time.strftime('%a %H:%M', time.localtime(data['updated']))}: "
          f"{data['snapshots']} snapshots, {data['sale_hours']} with sales estimates (firms up after a day or two)")
    print("listed = median listing price, sold at = average price of listings that sold\n")
    snipe = next(l for l in blizzard.HERE.joinpath("lists.txt").read_text().splitlines()
                 if l.startswith("Flip Snipe^"))
    names = [n.split(";")[0].strip('"') for n in snipe.split("^")[1:]]
    on_list = set()
    money = lambda c: blizzard.money(c) if c is not None else "-"
    print(f"{'Snipe list':32} {'listed':>9} {'sold at':>9} {'now':>9} {'sold/day':>9}")
    for name in names:
        ids = [i for i in blizzard.item_ids(name) if i in items]
        on_list.update(blizzard.item_ids(name))
        if not ids:
            print(f"{name[:32]:32} {'not listed this week':>39}")
            continue
        listed, sold_at, now, per_day = items[max(ids, key=lambda x: items[x][3])]
        print(f"{name[:32]:32} {money(listed):>9} {money(sold_at):>9} {money(now):>9} {per_day:>9.0f}")

    # Price = the lower of listed and sold at: cancelled or reposted pricey listings count
    # as sales, so sold at alone can read 10x high (Silverleaf: listed 35c, sold at 3s 52c)
    price = {i: min(v[0], v[1]) if v[0] else v[1] for i, v in items.items() if v[1]}
    print(f"\nBest items NOT on the list, selling at up to {blizzard.money(cap)}, ranked by gold sold per day")
    ranked = sorted((items[i][3] * p, i) for i, p in price.items() if p <= cap and i not in on_list)
    print(f"{'item':32} {'price':>9} {'sold/day':>9} {'gold/day':>9}")
    for turnover, i in reversed(ranked[-15:]):
        print(f"{blizzard.item_name(i)[:32]:32} {blizzard.money(price[i]):>9} {items[i][3]:>9.0f} {blizzard.money(turnover):>9}")

    # Vendor deals still there an hour later sit on items nobody camps: the ones you can win.
    # Check an item really sells to a merchant before buying lots (rogue poisons do not).
    vendor = {int(k): v for k, v in data.get("vendor", {}).items()}
    for title, comm in (("one-click buys (gear and other non-stackables)", 0), ("commodities (two-step buys)", 1)):
        print(f"\nVendor deals that lasted an hour: {title}")
        print(f"{'item':32} {'vendor':>9} {'under vendor':>12} {'lasted':>7} {'profit':>9} {'each':>7}")
        for profit, i in sorted(((v[4], i) for i, v in vendor.items() if v[1] == comm and v[3]), reverse=True)[:10]:
            price, _, n, lasted, _ = vendor[i]
            print(f"{blizzard.item_name(i)[:32]:32} {blizzard.money(price):>9} {n:>12} {lasted:>7} {blizzard.money(profit):>9} "
                  f"{blizzard.money(profit / lasted):>7}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["report"]:
        report(int(sys.argv[2]) if len(sys.argv) > 2 else 10000)
    else:
        pull()
