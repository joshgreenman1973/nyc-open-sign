#!/usr/bin/env python3
"""Rough coverage check, by borough: how many food listings this map has,
set against how many food service establishments the city health department
inspected in the two years before the data was pulled.

    python3 coverage.py      # reads data.json, writes coverage.json

This is a ratio of two counts, not a match rate. Nothing here pairs a map
listing with a health department record, and the two lists don't define a
food place the same way: the map's food kind includes bakeries, coffee shops,
ice cream and candy and chocolate shops, some of which the health department
doesn't inspect, and the health department's list includes places, like
school and office cafeterias, that rarely post hours on OpenStreetMap.

Sources:
- Borough Boundaries, NYC Open Data, dataset gthc-hcne
- DOHMH New York City Restaurant Inspection Results, NYC Open Data, 43nn-pn8j
"""
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BOROS = "https://data.cityofnewyork.us/resource/gthc-hcne.geojson"
DOHMH = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"


def get(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nyc-open-sign/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except Exception as e:                       # noqa: BLE001
            # Socrata answers anonymous throttling with 403; wait and retry.
            if i == tries - 1:
                raise
            print(f"  {e}; retrying")
            time.sleep(20 * (i + 1))


def inside(x, y, ring):
    hit = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def in_multipolygon(x, y, mp):
    for poly in mp:
        if inside(x, y, poly[0]) and not any(inside(x, y, h) for h in poly[1:]):
            return True
    return False


def main():
    data = json.load(open(os.path.join(HERE, "data.json")))
    pulled = dt.date.fromisoformat(data["generated"])
    since = pulled.replace(year=pulled.year - 2)
    food = data["kinds"].index("food")

    boros = get(BOROS)["features"]
    shapes = {f["properties"]["boroname"]: f["geometry"]["coordinates"] for f in boros}
    mapped = {b: 0 for b in shapes}
    outside = 0
    for lon, lat, k, *_ in data["p"]:
        if k != food:
            continue
        for b, mp in shapes.items():
            if in_multipolygon(lon, lat, mp):
                mapped[b] += 1
                break
        else:
            outside += 1   # on a pier or shoreline the borough outline misses

    q = urllib.parse.urlencode({
        "$select": "boro, count(distinct camis) as n",
        "$where": f"inspection_date >= '{since.isoformat()}'",
        "$group": "boro",
    })
    inspected = {r["boro"]: int(r["n"]) for r in get(f"{DOHMH}?{q}")}

    rows = []
    for b in ["Brooklyn", "Manhattan", "Queens", "Staten Island", "Bronx"]:
        rows.append({
            "borough": b,
            "map_food_listings": mapped[b],
            "dohmh_establishments_inspected": inspected[b],
            "ratio": round(mapped[b] / inspected[b], 3),
        })
    out = {
        "computed": dt.date.today().isoformat(),
        "map_data_pulled": pulled.isoformat(),
        "dohmh_inspections_since": since.isoformat(),
        "map_food_listings_outside_borough_outlines": outside,
        "note": "Ratio of two counts, not a match rate; see coverage.py.",
        "rows": rows,
    }
    with open(os.path.join(HERE, "coverage.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    for r in rows:
        print(f"  {r['borough']:<14} {r['map_food_listings']:>5} / "
              f"{r['dohmh_establishments_inspected']:>6} = {r['ratio']:.0%}")
    print(f"  {outside} food listings fell outside the borough outlines")


if __name__ == "__main__":
    main()
