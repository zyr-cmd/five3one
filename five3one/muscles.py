"""Muscle groups, the exercise map, set kinds, and lenses A (program) and B (session).

Counting convention: a set counts 1.0 for a muscle it trains as a primary mover and
0.5 as a secondary mover ("fractional" sets). Basis: Pelland et al., Sports Medicine
(67 studies, 2,058 participants) compared counting indirect sets as 1, 0.5 and 0 and
found 0.5 predicted hypertrophy and strength gains best. Only those three values were
tested. Which muscles an exercise trains, and as primary or secondary, is a judgement
recorded in DEFAULT_MAP; the state file can override any entry.

Only done sets count (parse.is_done). Listed-but-not-done sets are ignored everywhere.
"""

from collections import defaultdict
from datetime import timedelta

from .model import detect_blocks
from .parse import canonical_names, is_done, session_dates
from .text import norm

# (id, label). The list was set by the owner; the diagram has one region per id.
MUSCLES = [
    ("neck", "Neck"), ("traps", "Traps"), ("front_delts", "Front delts"),
    ("side_delts", "Side delts"), ("rear_delts", "Rear delts"), ("chest", "Chest"),
    ("serratus", "Serratus"), ("lats", "Lats"), ("mid_back", "Mid back"),
    ("lower_back", "Lower back"), ("abs", "Abs and obliques"), ("triceps", "Triceps"),
    ("biceps", "Biceps"), ("brachialis", "Brachialis"),
    ("brachioradialis", "Brachioradialis"), ("forearms", "Forearms"),
    ("glutes", "Glutes"), ("quads", "Quads"), ("hamstrings", "Hamstrings"),
    ("adductors", "Adductors"), ("calves", "Calves"), ("tibialis", "Tibialis"),
]
MUSCLE_IDS = [m for m, _ in MUSCLES]
LABEL = dict(MUSCLES)

_ROW = {"lats": 1.0, "mid_back": 1.0, "rear_delts": 0.5, "biceps": 0.5,
        "brachialis": 0.5, "brachioradialis": 0.5}
_PULLDOWN = {"lats": 1.0, "mid_back": 0.5, "biceps": 0.5, "brachialis": 0.5,
             "brachioradialis": 0.5}

# Keys are text.norm() of the exercise name (lower case, no spaces or hyphens).
DEFAULT_MAP = {
    "benchpress": {"chest": 1.0, "front_delts": 0.5, "triceps": 0.5},
    "militarypress": {"front_delts": 1.0, "side_delts": 0.5, "triceps": 0.5,
                      "traps": 0.5, "serratus": 0.5},
    "squat": {"quads": 1.0, "glutes": 1.0, "adductors": 0.5, "lower_back": 0.5},
    "deadlift": {"hamstrings": 1.0, "glutes": 1.0, "lower_back": 1.0, "quads": 0.5,
                 "traps": 0.5, "lats": 0.5, "forearms": 0.5},
    "row": _ROW, "chestsupportedrow": _ROW, "seatedcablerow": _ROW,
    "latpulldown": _PULLDOWN, "widegriplatpulldown": _PULLDOWN,
    "neutralgriplatpulldown": _PULLDOWN, "neutralgrippulldown": _PULLDOWN,
    "supinatedgriplatpulldown": _PULLDOWN,
    "facepulls": {"rear_delts": 1.0, "mid_back": 0.5},
    "reardeltfly": {"rear_delts": 1.0, "mid_back": 0.5},
    "dumbbelllateralraise": {"side_delts": 1.0},
    "pecfly": {"chest": 1.0, "front_delts": 0.5},
    "tricepsropepushdown": {"triceps": 1.0},
    "bicepsdumbbellcurl": {"biceps": 1.0, "brachialis": 0.5, "brachioradialis": 0.5},
    "hammercurl": {"brachialis": 1.0, "brachioradialis": 1.0, "biceps": 0.5},
    "reversegripcurls": {"brachioradialis": 1.0, "brachialis": 0.5, "biceps": 0.5,
                         "forearms": 0.5},
    "hanginglegraise": {"abs": 1.0},
    "pallofpress": {"abs": 1.0},
    "legextension": {"quads": 1.0},
    "calfraises": {"calves": 1.0},
}


class UnmappedError(Exception):
    """Done sets exist for exercises with no muscle mapping. Never guessed."""

    def __init__(self, names):
        self.names = sorted(names)
        super().__init__("no muscle mapping for: " + ", ".join(self.names))

    def fixes(self, state_path="STATE.json"):
        return ['map-set --state %s "%s" MUSCLE=1 [MUSCLE=0.5 ...]' % (state_path, n)
                for n in self.names]


def resolve_map(state=None):
    """Default map with the state file's overrides applied (keys normalised)."""
    emap = dict(DEFAULT_MAP)
    for name, weights in ((state or {}).get("exercise_map") or {}).items():
        emap[norm(name)] = dict(weights)
    return emap


def set_kind(e):
    """warmup | main | joker | bbb | accessory | other (see the package docstring)."""
    st = e["set_type"]
    if st == "Warm up":
        return "warmup" if e["is_main_lift_row"] else "accessory"
    if st == "Main":
        return "main"
    if st == "Joker sets":
        return "joker"
    if st == "Boring but BIG sets":
        return "bbb"
    if st == "":
        return "accessory"
    return "other"


def counted_sets(events, emap):
    """Done, non-warm-up sets as rows carrying their muscle weights.

    Returns (rows, other_count). Raises UnmappedError if any done set belongs to an
    exercise with no mapping. A row's `top` is True for the last done set of a Main
    row (the week's top or AMRAP set)."""
    names = canonical_names(events)
    rows, unmapped, other = [], set(), 0
    last_main = {}
    for e in events:
        kind = set_kind(e)
        if kind == "warmup" or not is_done(e):
            continue
        if kind == "other":
            other += 1
            continue
        weights = emap.get(norm(e["key"]))
        if weights is None:
            unmapped.add(names[e["key"]])
            continue
        row = {"date": e["date"], "key": e["key"], "name": names[e["key"]], "kind": kind,
               "reps": e["reps"], "weight": e["weight"], "top": False, "muscles": weights,
               "order": (e["row_idx"], e["set_index"])}
        rows.append(row)
        if kind == "main":
            k = (e["date"], e["key"], e["row_idx"])
            if k not in last_main or row["order"] > last_main[k]["order"]:
                last_main[k] = row
    if unmapped:
        raise UnmappedError(unmapped)
    for row in last_main.values():
        row["top"] = True
    return rows, other


def _fmt_set(r):
    return "%gx%s" % (r["weight"], r["reps"])


def _aggregate(rows):
    """{muscle: {sets, direct_sets, dates, exercises{name: {sets, weight, reps[]}}}}"""
    agg = {m: {"sets": 0.0, "direct_sets": 0, "dates": set(), "exercises": {}}
           for m in MUSCLE_IDS}
    for r in rows:
        for m, w in r["muscles"].items():
            a = agg[m]
            a["sets"] += w
            a["direct_sets"] += 1 if w >= 1.0 else 0
            a["dates"].add(r["date"])
            ex = a["exercises"].setdefault(r["name"], {"sets": 0, "weight": w, "done": []})
            ex["sets"] += 1
            ex["done"].append(_fmt_set(r))
    return agg


def _exercise_list(a):
    return [{"name": n, "sets": x["sets"], "muscle_weight": x["weight"], "done": x["done"]}
            for n, x in sorted(a["exercises"].items(), key=lambda kv: (-kv[1]["weight"], kv[0]))]


def lens_program(events, emap, as_of=None, weeks=4):
    """Lens A. Done sets per week per muscle over the last `weeks` calendar weeks
    ending at as_of (default: the last session date), within the current block."""
    rows, other = counted_sets(events, emap)
    end = as_of or session_dates(events)[-1]
    block_start = detect_blocks(events)[-1][0]
    start = max(block_start, end - timedelta(days=weeks * 7 - 1))
    span_weeks = max(((end - start).days + 1) / 7.0, 1 / 7.0)
    agg = _aggregate([r for r in rows if start <= r["date"] <= end])
    muscles = []
    for m in MUSCLE_IDS:
        a = agg[m]
        muscles.append({
            "muscle": m, "label": LABEL[m],
            "sets_per_week": round(a["sets"] / span_weeks, 1),
            "direct_sets_per_week": round(a["direct_sets"] / span_weeks, 1),
            "days_per_week": round(len(a["dates"]) / span_weeks, 1),
            "sets": a["sets"], "direct_sets": a["direct_sets"], "days": len(a["dates"]),
            "exercises": _exercise_list(a)})
    sessions = len({r["date"] for r in rows if start <= r["date"] <= end})
    return {"lens": "program", "window": {"start": str(start), "end": str(end),
                                          "weeks": round(span_weeks, 2), "sessions": sessions},
            "muscles": muscles, "uncounted_other_sets": other}


def lens_session(events, emap, date=None):
    """Lens B. Done sets per muscle for one session (default: the latest)."""
    rows, other = counted_sets(events, emap)
    dates = session_dates(events)
    target = date or dates[-1]
    if target not in dates:
        raise ValueError("No session on %s. Nearby: %s" % (
            target, [str(d) for d in dates if abs((d - target).days) <= 7]))
    agg = _aggregate([r for r in rows if r["date"] == target])
    muscles = [{"muscle": m, "label": LABEL[m], "sets": agg[m]["sets"],
                "direct_sets": agg[m]["direct_sets"], "exercises": _exercise_list(agg[m])}
               for m in MUSCLE_IDS]
    return {"lens": "session", "date": str(target), "muscles": muscles,
            "uncounted_other_sets": other}


def text_program(res):
    w = res["window"]
    out = ["Program: done sets per week, %s to %s (%.1f weeks, %d sessions)"
           % (w["start"], w["end"], w["weeks"], w["sessions"]),
           "%-18s%8s%8s%10s" % ("Muscle", "Sets/wk", "Direct", "Days/wk")]
    for m in sorted(res["muscles"], key=lambda x: (-x["sets_per_week"], x["label"])):
        out.append("%-18s%8.1f%8.1f%10.1f" % (m["label"], m["sets_per_week"],
                                               m["direct_sets_per_week"], m["days_per_week"]))
    out.append("(Sets/wk counts secondary work at half; Direct counts primary-mover sets only.)")
    return "\n".join(out)


def text_session(res):
    out = ["Session %s: done sets per muscle" % res["date"],
           "%-18s%6s%8s  %s" % ("Muscle", "Sets", "Direct", "From")]
    hit = [m for m in res["muscles"] if m["sets"] > 0]
    for m in sorted(hit, key=lambda x: (-x["sets"], x["label"])):
        src = ", ".join("%s x%d" % (e["name"], e["sets"]) for e in m["exercises"])
        out.append("%-18s%6.1f%8d  %s" % (m["label"], m["sets"], m["direct_sets"], src))
    idle = [m["label"] for m in res["muscles"] if m["sets"] == 0]
    if idle:
        out.append("Not trained: " + ", ".join(idle))
    return "\n".join(out)


def muscle_exercises(emap, key, primary_only=True):
    weights = emap.get(norm(key)) or {}
    return [m for m in MUSCLE_IDS if m in weights and (weights[m] >= 1.0 or not primary_only)]


def session_load(rows):
    """{date: [rows]} helper shared with the recovery lens."""
    by = defaultdict(list)
    for r in rows:
        by[r["date"]].append(r)
    return by
