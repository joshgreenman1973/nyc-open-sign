# Open Sign

Every New York City business that posts its opening hours on OpenStreetMap, lit on a dark map when it's open, for any minute of the week.

- `build.py` pulls every place inside the five boroughs with an `opening_hours` tag from Overpass, keeps the businesses, reads the hours into a weekly schedule and writes `data.json`. It refuses to overwrite the file on an empty result, a parse rate under 85% or a place count that falls by more than a quarter.
- `index.html` is the whole page: MapLibre for the faint basemap (CARTO vector tiles), deck.gl for the lights, drawn with additive blending so clusters of open places add up.
- `.github/workflows/refresh-data.yml` rebuilds the data every Monday.

Run locally:

    python3 build.py
    python3 -m http.server 8977

Link to a moment with a hash: `#fri-2330` is Friday at 11:30 p.m.
