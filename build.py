#!/usr/bin/env python3
"""Rebuild data.json: every New York City business on OpenStreetMap that posts
its opening hours, with those hours turned into a weekly schedule.

    python3 build.py              # fetch from Overpass, then build
    python3 build.py --raw FILE   # build from a saved Overpass response

OpenStreetMap's opening_hours tag is a small language of its own
("Mo-Fr 09:00-17:00; Sa 10:00-14:00; Su off"). The parser below handles the
forms that make up nearly all New York City entries and drops anything it
can't read rather than guessing. The share it drops is written into the data
file and shown on the page.

Fails loudly: an Overpass error, an empty result, a parse rate that has
collapsed, or a place count far below the last build all abort before
data.json is touched.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
ROUNDS = 4
ROUND_BACKOFF = [30, 90, 240]

# Relation 175905 is the five boroughs.
QUERY = """[out:json][timeout:250];
area(3600175905)->.nyc;
nwr["opening_hours"](area.nyc);
out center tags;
"""

MIN_PARSE_RATE = 0.85
MIN_RETAINED_SHARE = 0.75

# ---------------------------------------------------------------- kinds
# Five kinds of light. The colours on the page follow the kind of light each
# place actually throws: fluorescent delis, incandescent dining rooms, neon bars.
KINDS = ["food", "bars", "delis", "shops", "services"]

FOOD_AMENITY = {"restaurant", "fast_food", "cafe", "ice_cream", "food_court"}
FOOD_SHOP = {"bakery", "pastry", "coffee", "bagel", "doughnut", "tea",
             "confectionery", "chocolate"}
BAR_AMENITY = {"bar", "pub", "nightclub", "biergarten"}
DELI_SHOP = {"convenience", "supermarket", "deli", "grocery", "greengrocer",
             "chemist", "kiosk", "butcher", "seafood", "beverages",
             "alcohol", "wine", "tobacco"}
DELI_AMENITY = {"pharmacy", "fuel"}
SERVICE_AMENITY = {"bank", "clinic", "dentist", "doctors", "veterinary",
                   "money_transfer", "car_wash", "car_rental", "marketplace",
                   "cinema", "theatre", "bureau_de_change", "driving_school",
                   "language_school", "music_school", "dancing_school"}
SERVICE_LEISURE = {"fitness_centre", "sports_centre", "bowling_alley",
                   "amusement_arcade", "dance", "escape_game"}
SERVICE_TOURISM = {"gallery", "museum", "hotel", "hostel", "motel"}


def kind_of(t):
    a, s = t.get("amenity"), t.get("shop")
    if a in BAR_AMENITY:
        return "bars"
    if a in FOOD_AMENITY or s in FOOD_SHOP:
        return "food"
    if a in DELI_AMENITY or s in DELI_SHOP:
        return "delis"
    if s:
        return "shops"
    if (a in SERVICE_AMENITY or t.get("leisure") in SERVICE_LEISURE
            or t.get("tourism") in SERVICE_TOURISM or "office" in t
            or "craft" in t or "healthcare" in t):
        return "services"
    return None   # parks, libraries, toilets, bike docks, ATMs: not businesses


# ---------------------------------------------------------------- parser
DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY_RE = r"(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)"
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\+?$")
OPEN_END_RE = re.compile(r"^(\d{1,2}):(\d{2})\+$")


class Unreadable(Exception):
    pass


def parse_days(sel):
    """'Mo-Fr,Su' -> {0,1,2,3,4,6}. PH/SH (holidays) are dropped."""
    out = set()
    for part in re.split(r"\s*,\s*", sel.strip()):
        if part in ("PH", "SH"):
            continue
        m = re.fullmatch(r"(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?", part)
        if not m:
            raise Unreadable(part)
        a = DAYS.index(m.group(1))
        b = DAYS.index(m.group(2)) if m.group(2) else a
        i = a
        while True:
            out.add(i)
            if i == b:
                break
            i = (i + 1) % 7
    return out


def parse_times(spec):
    """'11:00-15:00,17:00-02:00' -> [(660,900),(1020,1560)], minutes from
    the day's midnight; a span past midnight runs over 1440."""
    spans = []
    for part in re.split(r"\s*,\s*", spec.strip()):
        m = TIME_RE.match(part)
        if m:
            h1, m1, h2, m2 = map(int, m.groups())
            s, e = h1 * 60 + m1, h2 * 60 + m2
            if e <= s:
                e += 1440
            if s >= 1440 or e > 2880:
                raise Unreadable(part)
            spans.append((s, e))
            continue
        m = OPEN_END_RE.match(part)
        if m:   # "17:00+": open-ended; count three hours
            s = int(m.group(1)) * 60 + int(m.group(2))
            spans.append((s, s + 180))
            continue
        raise Unreadable(part)
    return spans


def month_ok(prefix, today):
    """'Jul-Aug' or 'Apr-Oct' -> whether today's month falls inside."""
    m = re.fullmatch(r"(%s)(?:-(%s))?" % ("|".join(MONTHS), "|".join(MONTHS)), prefix)
    if not m:
        raise Unreadable(prefix)
    a = MONTHS.index(m.group(1))
    b = MONTHS.index(m.group(2)) if m.group(2) else a
    mo = today.month - 1
    return a <= mo <= b if a <= b else (mo >= a or mo <= b)


def parse(oh, today):
    """Return a 7-item list of day schedules (lists of spans), or raise."""
    oh = oh.strip()
    if oh == "24/7":
        return [[(0, 1440)] for _ in range(7)]
    # Several schedules for one place (store || pharmacy): keep the first,
    # which is the main business in every New York City case seen.
    oh = oh.split("||")[0]
    oh = re.sub(r'"[^"]*"', "", oh)              # comments
    oh = re.sub(r"\bopen\b", "", oh)
    oh = re.sub(r"(\d)\s+-\s*(\d)|(\d)\s*-\s+(\d)",
                lambda m: f"{m.group(1) or m.group(3)}-{m.group(2) or m.group(4)}", oh)
    # ", " between whole rules, when the comma follows a time
    oh = re.sub(r"(?<=\d|\+),\s*(?=%s\b)" % DAY_RE, "; ", oh)

    week = [[] for _ in range(7)]
    saw_rule = False
    for rule in (r.strip() for r in oh.split(";")):
        if not rule:
            continue
        if "[" in rule and re.search(r"\b(off|closed)$", rule):
            continue            # "Nov Th[4] off": Thanksgiving and the like
        # Month or date prefix: seasonal rule or a one-day exception.
        mm = re.match(r"^((?:%s)(?:\s*\d{1,2})?(?:-(?:%s)(?:\s*\d{1,2})?)?):?\s+(.*)$"
                      % ("|".join(MONTHS), "|".join(MONTHS)), rule)
        if mm:
            prefix, rest = mm.group(1), mm.group(2)
            if re.search(r"\d", prefix):
                continue        # "Dec 25 off": a holiday, not the usual week
            if not month_ok(prefix.replace(" ", ""), today):
                continue
            rule = rest
        if re.fullmatch(r"(?:PH|SH)(?:\s*,\s*(?:PH|SH))*(?:\s+.*)?", rule):
            continue            # holiday-only rule
        m = re.match(r"^(%s(?:\s*[-,]\s*%s)*)\s*(.*)$" % (DAY_RE, DAY_RE), rule)
        if m and m.group(1):
            days = parse_days(re.sub(r"\s+", "", m.group(1)))
            spec = m.group(2).strip()
        else:
            days, spec = set(range(7)), rule
        if not days:
            continue
        if spec in ("off", "closed"):
            spans = []
        elif spec == "24/7" or spec == "00:00-24:00":
            spans = [(0, 1440)]
        elif spec == "":
            raise Unreadable(rule)
        else:
            spans = parse_times(spec)
        for d in days:
            week[d] = list(spans)
        saw_rule = True
    if not saw_rule:
        raise Unreadable(oh)
    return week


def to_weekly(week):
    """Day schedules -> sorted, merged [start, end) pairs in minutes from
    Monday 00:00, wrapping Sunday-night spill into Monday."""
    W = 7 * 1440
    raw = []
    for d, spans in enumerate(week):
        for s, e in spans:
            s, e = d * 1440 + s, d * 1440 + e
            if e > W:
                raw.append((s, W))
                raw.append((0, e - W))
            else:
                raw.append((s, e))
    raw.sort()
    merged = []
    for s, e in raw:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [x for pair in merged for x in pair]


# ---------------------------------------------------------------- fetch
def fetch():
    last = None
    for rnd in range(ROUNDS):
        for endpoint in ENDPOINTS:
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=urllib.parse.urlencode({"data": QUERY}).encode(),
                    headers={"User-Agent": "nyc-open-sign/1.0 (github.com/joshgreenman1973)"},
                )
                with urllib.request.urlopen(req, timeout=300) as r:
                    payload = json.loads(r.read())
                if "elements" not in payload:
                    raise RuntimeError(f"no elements key: {str(payload)[:200]}")
                return payload
            except Exception as e:                  # noqa: BLE001
                last = e
                print(f"  round {rnd + 1}: {endpoint} failed ({e})", file=sys.stderr)
        if rnd < ROUNDS - 1:
            wait = ROUND_BACKOFF[min(rnd, len(ROUND_BACKOFF) - 1)]
            print(f"  all mirrors failed; waiting {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Overpass unavailable: {last}")


def main():
    if "--raw" in sys.argv:
        payload = json.load(open(sys.argv[sys.argv.index("--raw") + 1]))
    else:
        print("querying Overpass...")
        payload = fetch()
    els = payload["elements"]
    print(f"  {len(els)} elements with opening_hours")

    today = dt.date.today()
    sched_index, scheds = {}, []
    places, seen = [], set()
    tried = failed = 0
    by_kind_fail = {k: 0 for k in KINDS}
    for el in els:
        t = el.get("tags", {})
        k = kind_of(t)
        if not k:
            continue
        if "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        elif "lat" in el:
            lat, lon = el["lat"], el["lon"]
        else:
            continue
        key = (el["type"], el["id"])
        if key in seen:
            continue
        seen.add(key)
        tried += 1
        try:
            weekly = to_weekly(parse(t["opening_hours"], today))
        except (Unreadable, ValueError):
            failed += 1
            by_kind_fail[k] += 1
            continue
        if not weekly:
            continue        # posted as closed every day
        sig = tuple(weekly)
        if sig not in sched_index:
            sched_index[sig] = len(scheds)
            scheds.append(weekly)
        name = t.get("name") or t.get("brand") or ""
        places.append([round(lon, 5), round(lat, 5), KINDS.index(k),
                       sched_index[sig], name])

    rate = 1 - failed / tried if tried else 0
    print(f"  {tried} businesses, {failed} unreadable ({rate:.1%} read), "
          f"{len(places)} mapped, {len(scheds)} distinct schedules")
    if not places:
        raise SystemExit("FAILED: no places — refusing to overwrite")
    if rate < MIN_PARSE_RATE:
        raise SystemExit(f"FAILED: parse rate {rate:.1%} below {MIN_PARSE_RATE:.0%}")
    if os.path.exists(OUT):
        was = len(json.load(open(OUT)).get("p", []))
        if was and len(places) < was * MIN_RETAINED_SHARE:
            raise SystemExit(f"FAILED: {len(places)} places, down from {was}")

    places.sort(key=lambda p: (p[2], p[1]))
    out = {
        "generated": today.isoformat(),
        "kinds": KINDS,
        "tried": tried,
        "unreadable": failed,
        "s": scheds,
        "p": places,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, OUT)
    print(f"wrote data.json ({os.path.getsize(OUT) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
