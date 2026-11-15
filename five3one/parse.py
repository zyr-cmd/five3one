"""CSV reading. One event dict per individual set. Quirks: see the package docstring."""

import argparse
import csv
from datetime import datetime

EXPECTED_COLUMNS = ["Date", "Name", "Set", "SetCompleted", "Reps", "Weights",
                    "CycleNr", "WeekNr", "Notes"]
MAIN_SET_TYPES = {"Warm up", "Main", "Boring but BIG sets", "Joker sets"}
STRONG_MAIN_TYPES = {"Main", "Boring but BIG sets", "Joker sets"}


def parse_date(s):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError("not a YYYY-MM-DD date: %r" % s)


def split_field(s):
    return [x.strip() for x in s.split(";")] if s and s.strip() else []


def cell(row, col):
    return (row.get(col) or "").strip()


def load_events(csv_path):
    """Return (events, errors, warnings). One event dict per individual set."""
    events, errors, warnings = [], [], []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in EXPECTED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            return events, ["missing columns: %s" % missing], warnings
        for row_idx, row in enumerate(reader):
            line = reader.line_num
            try:
                d = parse_date(cell(row, "Date"))
                cycle_raw, week_raw = cell(row, "CycleNr"), cell(row, "WeekNr")
                cycle = int(cycle_raw) if cycle_raw else None
                week = int(week_raw) if week_raw else None
                reps_l = [int(x) for x in split_field(cell(row, "Reps"))]
                weights_l = [float(x) for x in split_field(cell(row, "Weights"))]
            except (ValueError, argparse.ArgumentTypeError) as exc:
                errors.append("line %d: %s" % (line, exc))
                continue
            done_l = [x.lower() == "true" for x in split_field(cell(row, "SetCompleted"))]
            name_raw = cell(row, "Name")
            n = max(len(reps_l), len(weights_l), len(done_l))
            if len({len(reps_l), len(weights_l), len(done_l)}) > 1:
                warnings.append("line %d: %s on %s has mismatched set arrays "
                                "(reps %d, weights %d, completed %d)"
                                % (line, name_raw, d, len(reps_l), len(weights_l), len(done_l)))
            for i in range(n):
                events.append({
                    "date": d, "name_raw": name_raw, "key": name_raw.lower(),
                    "set_type": cell(row, "Set"), "is_main_lift_row": False,
                    "set_index": i,
                    "reps": reps_l[i] if i < len(reps_l) else None,
                    "weight": weights_l[i] if i < len(weights_l) else None,
                    "completed": done_l[i] if i < len(done_l) else None,
                    "cycle": cycle, "week": week, "notes": cell(row, "Notes"),
                    "row_idx": row_idx,
                })
    strong = {e["key"] for e in events if e["set_type"] in STRONG_MAIN_TYPES}
    for e in events:
        e["is_main_lift_row"] = e["key"] in strong and e["set_type"] in MAIN_SET_TYPES
    return events, errors, warnings


def raw_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        return cols, list(reader)


def is_done(e):
    """The owner's rule for every set type: ticked, and reps above zero."""
    return e["completed"] is True and (e["reps"] or 0) > 0


def is_not_done(e):
    """Explicitly not done: unticked, or ticked with 0 reps. A blank tick is neither
    done nor not done (status unknown). Not done never means failed."""
    return e["completed"] is False or (e["completed"] is True and e["reps"] == 0)


def canonical_names(events):
    latest = {}
    for e in events:
        cur = latest.get(e["key"])
        if cur is None or e["date"] >= cur[0]:
            latest[e["key"]] = (e["date"], e["name_raw"])
    return {k: v[1] for k, v in latest.items()}


def main_lift_keys(events):
    return sorted({e["key"] for e in events if e["is_main_lift_row"]})


def session_dates(events):
    return sorted({e["date"] for e in events})


def events_for_dates(events, dates):
    dateset = set(dates)
    return [e for e in events if e["date"] in dateset]


def group_rows(events):
    """[(date, key, set_type, [sets in order])] in first-seen order."""
    order, groups = [], {}
    for e in events:
        k = (e["date"], e["key"], e["set_type"])
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(e)
    return [(k[0], k[1], k[2], sorted(groups[k], key=lambda x: (x["row_idx"], x["set_index"])))
            for k in order]
