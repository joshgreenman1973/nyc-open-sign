#!/usr/bin/env python3
"""Checks the opening_hours parser against hand-worked examples, including
the two cases a Nov. 4, 2026 fact-check raised. Run:

    python3 test_parser.py
"""
import datetime as dt
from build import parse, to_weekly, Unreadable

NOV = dt.date(2026, 11, 4)
JUL = dt.date(2026, 7, 15)
H = lambda h, m=0: h * 60 + m
D = 1440

CASES = [
    # fact-check case 1: an additional rule ("," before a day) adds hours
    ("Mo-Fr 09:00-12:00, Mo-Fr 13:00-17:00", NOV,
     [x for d in range(5) for x in (d*D+H(9), d*D+H(12), d*D+H(13), d*D+H(17))]),
    # without the Tuesday rule the spill stays
    ("Mo 20:00-02:00", NOV, [H(20), D + H(2)]),
    # a normal rule replaces, an additional one adds
    ("Mo-Fr 09:00-17:00; Fr 10:00-12:00", NOV,
     [x for d in range(4) for x in (d*D+H(9), d*D+H(17))] + [4*D+H(10), 4*D+H(12)]),
    ("Mo-Fr 09:00-17:00, Fr 18:00-20:00", NOV,
     [x for d in range(4) for x in (d*D+H(9), d*D+H(17))] + [4*D+H(9), 4*D+H(17), 4*D+H(18), 4*D+H(20)]),
    # comma between times inside one rule
    ("Mo 11:00-15:00,17:00-22:00", NOV, [H(11), H(15), H(17), H(22)]),
    # Sunday night spills into Monday morning
    ("Su 22:00-03:00", NOV, [0, H(3), 6*D+H(22), 7*D]),
    # fallback: applies only to days the main rules left out
    ("Mo-Fr 09:00-17:00 || Sa 10:00-14:00", NOV,
     [x for d in range(5) for x in (d*D+H(9), d*D+H(17))] + [5*D+H(10), 5*D+H(14)]),
    ("Mo-Sa 09:00-17:00 || Sa 10:00-14:00", NOV,
     [x for d in range(6) for x in (d*D+H(9), d*D+H(17))]),
    # a fallback fills times, not just days: the store's hours around the
    # pharmacy's
    ('Mo-Fr 09:00-19:00 open "Pharmacy" || Mo-Fr 07:00-21:00 open "Store"', NOV,
     [x for d in range(5) for x in (d*D+H(7), d*D+H(21))]),
    # an "off" in the main rules is a time spoken for; the fallback can't reopen it
    ("Mo-Fr 09:00-17:00; Sa off || Sa-Su 10:00-14:00", NOV,
     [x for d in range(5) for x in (d*D+H(9), d*D+H(17))] + [6*D+H(10), 6*D+H(14)]),
    # a comment after the hours doesn't hide an additional rule
    ('Mo 12:00-14:00 "call us", We 16:00-18:00', NOV, [H(12), H(14), 2*D+H(16), 2*D+H(18)]),
    ('Mo-Fr 09:00-17:00 || "by appointment"', NOV,
     [x for d in range(5) for x in (d*D+H(9), d*D+H(17))]),
    # seasonal rules apply by the month the data is pulled
    ("Mo-Su 10:00-18:00; Jun-Aug Mo-Su 10:00-21:00", JUL,
     [x for d in range(7) for x in (d*D+H(10), d*D+H(21))]),
    ("Mo-Su 10:00-18:00; Jun-Aug Mo-Su 10:00-21:00", NOV,
     [x for d in range(7) for x in (d*D+H(10), d*D+H(18))]),
    # holidays ignored, open-ended counted as three hours, 24/7
    ("Mo-Fr 08:00-18:00; PH off", NOV,
     [x for d in range(5) for x in (d*D+H(8), d*D+H(18))]),
    ("Fr 22:00+", NOV, [4*D+H(22), 5*D+H(1)]),
    ("24/7", NOV, [0, 7*D]),
    ("Mo-Su 00:00-24:00; We off", NOV, [0, 2*D, 3*D, 7*D]),
]

# The specification's own example: strictly, a later rule for Sunday cancels
# Saturday night's hours past midnight, "which was probably not intended."
MIDNIGHT = [
    ("Sa 16:00-03:00; Su 16:00-23:00", True, [5*D+H(16), 6*D, 6*D+H(16), 6*D+H(23)]),
    ("Sa 16:00-03:00; Su 16:00-23:00", False, [5*D+H(16), 6*D+H(3), 6*D+H(16), 6*D+H(23)]),
    ("Sa 16:00-03:00, Su 16:00-23:00", True, [5*D+H(16), 6*D+H(3), 6*D+H(16), 6*D+H(23)]),
    # fact-check case 2: strictly, "Tu off" also closes Monday night after
    # midnight. The map keeps those hours (STRICT_MIDNIGHT = False).
    ("Mo 20:00-02:00; Tu off", True, [H(20), D]),
    ("Mo 20:00-02:00; Tu off", False, [H(20), D + H(2)]),
    ("Fr 17:30-01:00; Sa off", True, [4*D+H(17,30), 5*D]),
    ("Fr 17:30-01:00; Sa off", False, [4*D+H(17,30), 5*D+H(1)]),
]

UNREADABLE = ["by appointment", "Mo-Fr", "sunrise-sunset"]

bad = 0
for oh, day, want in CASES:
    got = to_weekly(parse(oh, day))
    if got != want:
        bad += 1
        print(f"FAIL {oh!r}\n  want {want}\n  got  {got}")
for oh, strict, want in MIDNIGHT:
    got = to_weekly(parse(oh, NOV, strict_midnight=strict))
    if got != want:
        bad += 1
        print(f"FAIL {oh!r} strict={strict}\n  want {want}\n  got  {got}")
for oh in UNREADABLE:
    try:
        parse(oh, NOV)
        bad += 1
        print(f"FAIL {oh!r} should be unreadable")
    except Unreadable:
        pass
total = len(CASES) + len(MIDNIGHT) + len(UNREADABLE)
print(f"{total - bad} of {total} passed")
raise SystemExit(1 if bad else 0)
