"""Derived training facts: blocks, e1RM, training maxes, lift lookup."""

from collections import defaultdict

from .parse import canonical_names, group_rows, main_lift_keys, session_dates
from .text import norm

BLOCK_GAP_DAYS = 21


def epley(weight, reps):
    if weight is None or reps is None:
        return None
    return round(weight * (1 + reps / 30), 1)


def detect_blocks(events, gap_days=BLOCK_GAP_DAYS):
    dates = session_dates(events)
    blocks = [[dates[0]]]
    for prev, cur in zip(dates, dates[1:]):
        if (cur - prev).days >= gap_days:
            blocks.append([])
        blocks[-1].append(cur)
    return [(b[0], b[-1], b) for b in blocks]


def top_e1rm(sets):
    top = sets[-1]
    return None if top["completed"] is False else epley(top["weight"], top["reps"])


def e1rm_history(events):
    hist = defaultdict(list)
    for d, key, st, sets in group_rows(events):
        if st == "Main":
            e = top_e1rm(sets)
            if e is not None:
                hist[key].append((d, e))
    return hist


# Standard 5/3/1 main-set percentages of the training max, by week.
WEEK_PCTS = {1: (0.65, 0.75, 0.85), 2: (0.70, 0.80, 0.90), 3: (0.75, 0.85, 0.95)}
TM_SPREAD_LIMIT = 0.10  # implied TMs from the 3 sets must agree within 10%


def round_to(x, step=2.5):
    return round(round(x / step) * step, 2)


def derive_training_maxes(events, names):
    """{lift name: {tm, implied, date, cycle, week}} from each main lift's latest
    week-1/2/3 Main row. The export has no TM column, so the TM is derived: the
    third main set (the top % set; extra sets after it are ignored) divided by
    that week's top percentage, rounded to 2.5. tm is None ("unclear") when the
    three sets imply TMs more than 10% apart, i.e. the row doesn't follow the
    standard percentages."""
    latest = {}
    for d, key, st, sets in group_rows(events):
        if (st == "Main" and sets[0]["is_main_lift_row"] and sets[0]["week"] in WEEK_PCTS
                and sets[0]["cycle"] not in (None, -1) and len(sets) >= 3
                and all(s["weight"] for s in sets[:3])):
            latest[key] = (d, sets)
    out = {}
    for key in sorted(latest, key=lambda k: names[k]):
        d, sets = latest[key]
        pcts = WEEK_PCTS[sets[0]["week"]]
        implied = [round(s["weight"] / p, 1) for s, p in zip(sets[:3], pcts)]
        consistent = (max(implied) - min(implied)) <= TM_SPREAD_LIMIT * max(implied)
        out[names[key]] = {"tm": round_to(implied[2]) if consistent else None,
                           "implied": implied, "date": str(d),
                           "cycle": sets[0]["cycle"], "week": sets[0]["week"]}
    return out


def resolve_lift(events, name):
    names = canonical_names(events)
    q = norm(name)
    keys = main_lift_keys(events)
    exact = [k for k in keys if norm(k) == q]
    matches = exact or [k for k in keys if q in norm(k)]
    if not matches:
        raise ValueError("No main lift matching '%s'. Main lifts: %s"
                         % (name, [names[k] for k in keys]))
    if len(matches) > 1:
        raise ValueError("Ambiguous '%s': %s" % (name, [names[m] for m in matches]))
    return matches[0]
