"""Formatting helpers shared by the commands."""

import json
import sys

from .parse import is_not_done


def fmt(x):
    return "-" if x is None else "%g" % x


def norm(s):
    return "".join(s.lower().split()).replace("-", "")


def short_note(text, limit=240):
    text = " / ".join(p.strip() for p in text.splitlines() if p.strip())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def die(args, msg):
    if getattr(args, "json", False):
        print(json.dumps({"error": msg}))
    else:
        print(msg, file=sys.stderr)
    return 1


def fmt_sets(sets):
    return " ".join("%sx%s%s" % (fmt(s["weight"]), s["reps"],
                                 "✗" if is_not_done(s) else "")
                    for s in sets)


def fmt_bbb(sets):
    ws, rs = {s["weight"] for s in sets}, {s["reps"] for s in sets}
    if len(ws) == 1 and len(rs) == 1 and not any(is_not_done(s) for s in sets):
        return "%dx%s @%skg" % (len(sets), sets[0]["reps"], fmt(sets[0]["weight"]))
    return fmt_sets(sets)
