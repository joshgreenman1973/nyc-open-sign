# Open Sign

New York City shops, restaurants, bars, offices and other places whose OpenStreetMap listings include opening hours, lit on a dark map when they're listed as open, for any minute of the week.

- `build.py` pulls every place inside the five boroughs with an `opening_hours` tag from Overpass, keeps five groups of places (dropping government offices and same-name duplicates within about 25 meters), reads the hours into a weekly schedule and writes `data.json`. It refuses to overwrite the file on an empty result, a parse rate under 85% or a place count that falls by more than a quarter.
- `index.html` is the whole page: MapLibre for the faint basemap (CARTO vector tiles), deck.gl for the lights, drawn with additive blending so clusters of open places add up.
- `test_parser.py` checks the hours parser against worked examples: `python3 test_parser.py`.
- `coverage.py` writes `coverage.json`, the borough-by-borough count of the map's food listings against restaurants the health department inspected. It's a ratio of two counts, not a match rate, and is run by hand.
- `.github/workflows/refresh-data.yml` is scheduled to rebuild the data every Monday.

Run locally:

    python3 build.py
    python3 -m http.server 8977

Link to a moment with a hash: `#fri-2330` is Friday at 11:30 p.m.
