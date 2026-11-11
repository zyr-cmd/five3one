#!/usr/bin/env python3
"""
five3one.py - Read a Five3One (5/3/1 BBB) CSV export without re-deriving its quirks.

Stdlib only, deterministic, no network. Point it at an export and get correct
figures in one call instead of reading the raw CSV.

USAGE
  python3 five3one.py CSV COMMAND [options]       (--json works anywhere)

AGENT ENTRY POINTS
  status  [--as-of YYYY-MM-DD] [--stale-days N]
        Start-of-session check. Last session, days since, current cycle/week
        (taken from the most recent main-lift session), main lifts done and
        remaining this week, flags on the last 2 sessions.
        Also prints derived training maxes per main lift (see derive_training_maxes;
        the export has no TM column). Unticked sets are reported as "not done".
        Pass --as-of with the user's local date (the container clock is UTC).
        Alias: summary.
  report  [--as-of YYYY-MM-DD] [--out PATH]
        The whole progress.md in one go: header, status and default recap in code
        blocks. Writes to PATH with --out, else prints. Use this to regenerate
        progress.md after an export instead of stitching outputs by hand.
  recap   [--days N | --since YYYY-MM-DD]
        Session-by-session recap (default: 14 days before the last session):
        main sets, top-set e1RM vs previous, jokers, BBB, accessory ticks, notes.
  ingest  [--stored OLD.csv] [--out PATH] [--allow-missing]
        CSV is the NEW export. Validates it, compares with the stored copy
        (new sessions, changed rows, rows missing = data loss) and, only if
        --out is given and validation passes, writes the new export to PATH.
        Without --out it is a dry run.

DRILL-DOWN COMMANDS
  session   [--date YYYY-MM-DD]   Full detail of one session (default: latest).
  lift      --name NAME [--last N]  Main-set progression plus BBB history for one lift.
  cycle     [--block N] [--cycle N]  Week-by-week top sets. Default: latest block,
            latest cycle. --block is 0-indexed. (--latest is accepted, a no-op.)
  accessory [--name NAME] [--since YYYY-MM-DD]  Accessory volume per session.
  adherence [--since YYYY-MM-DD]  Completed vs not-completed sets.
  list-lifts                      Every exercise name, flagging spelling variants.
  dump      [--date YYYY-MM-DD]   Parsed per-set rows, to check how an export is read.

ERRORS  Non-zero exit. With --json the error is {"error": "..."} on stdout.
EXIT CODES  0 ok, 1 error (bad CSV, rejected ingest, unknown lift), 2 usage.

CSV QUIRKS (verified against real exports Aug-Nov 2026; re-verify if the format changes)
1. Columns: Date, Name, Set, SetCompleted, Reps, Weights, CycleNr, WeekNr, Notes.
   Reps / Weights / SetCompleted are semicolon-delimited PARALLEL arrays: one
   row holds several sets. Notes can contain quoted newlines.
2. Main lifts are identified STRUCTURALLY: an exercise that appears with Set in
   {Main, Boring but BIG sets, Joker sets}. A "Warm up" row alone does not make
   a main lift. Set == '' is an accessory.
3. CycleNr is NOT a global id: it restarts after breaks. Training "blocks" are
   segmented by date gaps instead (a gap of 21+ days starts a new block).
4. WeekNr == 0 is overloaded: with CycleNr == -1 it is an accessory-only day;
   with a real CycleNr it is a deload / max-test day.
5. Exercise names drift in case/whitespace ("hammer curl" vs "Hammer Curl").
   Grouping uses strip().lower(); the most RECENTLY used spelling is displayed.
   Genuinely different names ("Row" vs "Chest-Supported Row") stay separate.
6. The last set of a Main row is the week's top / AMRAP set; e1RM = Epley
   w * (1 + reps / 30) on that set. Compare e1RM across weeks only roughly
   (different rep targets). If a template's last main set is not an AMRAP, the
   e1RM is not meaningful.
7. SetCompleted is per set. Accessory sets are often left unticked even when
   done, so accessory adherence is NOT a reliable measure; main-lift rows are.
8. BBB for a lift is done on ANOTHER lift's main day (frequency swap), so a
   lift's BBB history is not on the same dates as its main sets.
"""

import argparse
import contextlib
import csv
import io
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

EXPECTED_COLUMNS = ["Date", "Name", "Set", "SetCompleted", "Reps", "Weights",
                    "CycleNr", "WeekNr", "Notes"]
MAIN_SET_TYPES = {"Warm up", "Main", "Boring but BIG sets", "Joker sets"}
STRONG_MAIN_TYPES = {"Main", "Boring but BIG sets", "Joker sets"}
BLOCK_GAP_DAYS = 21


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def parse_date(s):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError("not a YYYY-MM-DD date: %r" % s)


def split_field(s):
    return [x.strip() for x in s.split(";")] if s and s.strip() else []


def cell(row, col):
    return (row.get(col) or "").strip()


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


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

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


def canonical_names(events):
    latest = {}
    for e in events:
        cur = latest.get(e["key"])
        if cur is None or e["date"] >= cur[0]:
            latest[e["key"]] = (e["date"], e["name_raw"])
    return {k: v[1] for k, v in latest.items()}


def main_lift_keys(events):
    return sorted({e["key"] for e in events if e["is_main_lift_row"]})


def epley(weight, reps):
    if weight is None or reps is None:
        return None
    return round(weight * (1 + reps / 30), 1)


def session_dates(events):
    return sorted({e["date"] for e in events})


def detect_blocks(events, gap_days=BLOCK_GAP_DAYS):
    dates = session_dates(events)
    blocks = [[dates[0]]]
    for prev, cur in zip(dates, dates[1:]):
        if (cur - prev).days >= gap_days:
            blocks.append([])
        blocks[-1].append(cur)
    return [(b[0], b[-1], b) for b in blocks]


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


def fmt_sets(sets):
    return " ".join("%sx%s%s" % (fmt(s["weight"]), s["reps"],
                                 "" if s["completed"] is not False else "✗")
                    for s in sets)


def fmt_bbb(sets):
    ws, rs = {s["weight"] for s in sets}, {s["reps"] for s in sets}
    if len(ws) == 1 and len(rs) == 1 and all(s["completed"] is not False for s in sets):
        return "%dx%s @%skg" % (len(sets), sets[0]["reps"], fmt(sets[0]["weight"]))
    return fmt_sets(sets)


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


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------

def cmd_status(events, args):
    names = canonical_names(events)
    today = args.as_of or date.today()
    dates = session_dates(events)
    last = dates[-1]
    days_since = (today - last).days
    blocks = detect_blocks(events)
    blk = blocks[-1]
    blk_events = events_for_dates(events, blk[2])
    main_rows = [e for e in blk_events if e["set_type"] == "Main" and e["cycle"] not in (None, -1)]

    cycle = week = None
    done, remaining = {}, []
    if main_rows:
        latest = max(main_rows, key=lambda e: (e["date"], e["row_idx"]))
        cycle, week = latest["cycle"], latest["week"]
        groups = group_rows(blk_events)
        for d, key, st, sets in groups:
            if st == "Main" and sets[0]["cycle"] == cycle and sets[0]["week"] == week:
                done.setdefault(key, {"date": str(d), "main": fmt_sets(sets),
                                      "e1rm": top_e1rm(sets), "jokers": None})
        for d, key, st, sets in groups:
            if st == "Joker sets" and key in done and str(d) == done[key]["date"]:
                done[key]["jokers"] = fmt_sets(sets)
        last_main = {}
        for e in main_rows:
            last_main[e["key"]] = max(last_main.get(e["key"], e["date"]), e["date"])
        remaining = sorted((k for k in last_main if k not in done), key=lambda k: last_main[k])
        remaining = [{"lift": names[k], "last_main": str(last_main[k])} for k in remaining]

    flags = []
    recent = set(dates[-2:])
    for d, key, st, sets in group_rows(events):
        if d in recent and st in ("Main", "Joker sets", "Boring but BIG sets"):
            bad = [s for s in sets if s["completed"] is False]
            if bad:
                flags.append("%s %s %s: not done (unticked) %s (of %d sets)"
                             % (d, names[key], st, fmt_sets(bad).replace("✗", ""), len(sets)))

    tms = derive_training_maxes(blk_events, names)
    last_28 = [d for d in dates if 0 <= (today - d).days <= 28]
    result = {
        "training_maxes": tms,
        "as_of": str(today), "last_session": str(last), "days_since_last_session": days_since,
        "stale": days_since >= args.stale_days,
        "block_started": str(blk[0]), "block_sessions": len(blk[2]),
        "cycle": cycle, "week": week,
        "done_this_week": {names[k]: v for k, v in done.items()},
        "remaining_this_week": remaining,
        "flags_last_2_sessions": flags,
        "sessions_last_28_days": len(last_28),
        "total_sessions": len(dates), "date_range": [str(dates[0]), str(last)],
        "training_blocks": len(blocks),
        "main_lifts": [names[k] for k in main_lift_keys(events)],
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print("As of %s: last session %s (%d day%s ago)"
          % (today, last, days_since, "" if days_since == 1 else "s"))
    if result["stale"]:
        print("STALE? %d+ days since the last logged session. If he has trained since, "
              "ask for a fresh export before advising." % args.stale_days)
    if cycle is not None:
        print("Position: Cycle %s, Week %s (block started %s, %d sessions)"
              % (cycle, week, blk[0], len(blk[2])))
        print("Done this week:")
        for name, v in result["done_this_week"].items():
            line = "  %s %s: %s" % (name, v["date"], v["main"])
            if v["jokers"]:
                line += " | jokers %s" % v["jokers"]
            print(line)
        if remaining:
            print("Remaining this week (longest since last trained first): "
                  + ", ".join("%s (last %s)" % (r["lift"], r["last_main"]) for r in remaining))
        else:
            print("Week complete: all main lifts done.")
    else:
        print("No main-lift cycle data in the current block yet.")
    if tms:
        print("Training maxes (derived: top main set / week %, nearest 2.5; from each lift's latest main session):")
        print("  " + ", ".join(
            "%s %s (C%s/W%s %s)" % (name, "unclear" if v["tm"] is None else "~%g" % v["tm"],
                                    v["cycle"], v["week"], v["date"])
            for name, v in tms.items()))
    if flags:
        print("Flags (last 2 sessions):")
        for f_ in flags:
            print("  " + f_)
    print("Frequency: %d sessions in last 28 days (~%.1f/week); %d sessions logged, %s to %s"
          % (len(last_28), len(last_28) / 4, len(dates), dates[0], last))


# --------------------------------------------------------------------------
# recap
# --------------------------------------------------------------------------

def cmd_recap(events, args):
    names = canonical_names(events)
    dates = session_dates(events)
    cutoff = args.since if args.since else dates[-1] - timedelta(days=args.days)
    window = [d for d in dates if d >= cutoff]
    hist = e1rm_history(events)
    groups = group_rows(events)
    sessions = []
    for d in window:
        day = [g for g in groups if g[0] == d]
        real = [g for g in day if g[3][0]["cycle"] not in (None, -1)]
        cyc = real[0][3][0]["cycle"] if real else None
        wk = real[0][3][0]["week"] if real else None
        lines, notes = [], []
        acc_total = acc_ticked = 0
        acc_names = []
        for _, key, st, sets in day:
            name = names[key]
            if st == "Main" and sets[0]["is_main_lift_row"]:
                e = top_e1rm(sets)
                prior = [v for (dd, v) in hist[key] if dd < d]
                extra = ""
                if e is not None and prior:
                    extra = " (prev %s, %+.1f%s)" % (prior[-1], e - prior[-1],
                                                      ", PR" if e > max(prior) else "")
                elif e is not None:
                    extra = " (first logged)"
                lines.append("%s main: %s | top e1RM %s%s" % (name, fmt_sets(sets), fmt(e), extra))
            elif st == "Joker sets" and sets[0]["is_main_lift_row"]:
                lines.append("%s jokers: %s" % (name, fmt_sets(sets)))
            elif st == "Boring but BIG sets" and sets[0]["is_main_lift_row"]:
                lines.append("%s BBB: %s" % (name, fmt_bbb(sets)))
            elif not sets[0]["is_main_lift_row"]:
                acc_total += len(sets)
                t = sum(1 for s in sets if s["completed"])
                acc_ticked += t
                if t:
                    acc_names.append("%s %d/%d" % (name, t, len(sets)))
            if sets[0]["notes"]:
                notes.append("[%s] %s" % (name, short_note(sets[0]["notes"])))
        if acc_total:
            lines.append("accessories ticked %d/%d sets%s"
                         % (acc_ticked, acc_total, " (" + ", ".join(acc_names) + ")" if acc_names else ""))
        sessions.append({"date": str(d), "cycle": cyc, "week": wk, "lines": lines, "notes": notes})
    if args.json:
        print(json.dumps({"since": str(cutoff), "sessions": sessions}, indent=2))
        return
    print("Recap since %s (%d sessions); e1RM comparisons are rough across weeks" % (cutoff, len(sessions)))
    for s in sessions:
        cw = " (C%s/W%s)" % (s["cycle"], s["week"]) if s["cycle"] is not None else " (accessory day)"
        print(s["date"] + cw)
        for ln in s["lines"]:
            print("  " + ln)
        for n in s["notes"]:
            print("  note " + n)


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

REPORT_HEADER = ("# Progress\n\nGenerated by five3one.py from workouts.csv (last logged session %s), "
                 "as of %s local date. Pure script output: overwrite whole on each export. "
                 "Hand-written plans live in weightlifting.md. If he has trained since, ask for a "
                 "fresh export and regenerate (see log-update.md).\n")


def _capture(fn, events, ns):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(events, ns)
    return buf.getvalue()


def build_report(events, as_of, stale_days=3, recap_days=14):
    today = as_of or date.today()
    status = _capture(cmd_status, events, argparse.Namespace(
        as_of=today, stale_days=stale_days, json=False))
    recap = _capture(cmd_recap, events, argparse.Namespace(
        as_of=today, days=recap_days, since=None, json=False))
    return (REPORT_HEADER % (session_dates(events)[-1], today)
            + "\n## Status\n```\n" + status + "```\n"
            + "\n## Recap (%d days before last session)\n```\n" % recap_days + recap + "```\n")


def cmd_report(events, args):
    text = build_report(events, args.as_of, args.stale_days)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except OSError as exc:
            return die(args, "cannot write %s: %s" % (args.out, exc))
    if args.json:
        print(json.dumps({"wrote": args.out, "markdown": text}, indent=2))
    elif args.out:
        print("wrote %s" % args.out)
    else:
        print(text, end="")


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------

def raw_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        return cols, list(reader)


def row_map(rows):
    seen, out = Counter(), {}
    for r in rows:
        k = (cell(r, "Date"), cell(r, "Name").lower(), cell(r, "Set"))
        seen[k] += 1
        out[k + (seen[k],)] = tuple(cell(r, c) for c in
                                    ("SetCompleted", "Reps", "Weights", "CycleNr", "WeekNr", "Notes"))
    return out


def cmd_ingest(args):
    errors, info = [], []
    result = {"valid": False, "errors": errors, "info": info, "new_sessions": [],
              "changed_rows": 0, "missing_rows": 0, "wrote": None}
    try:
        events, perrs, warns = load_events(args.csv)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return die(args, "REJECTED: cannot read %s: %s" % (args.csv, exc))
    errors.extend(perrs)
    if not events and not errors:
        errors.append("no data rows")
    rows = []
    if not errors:
        _, rows = raw_rows(args.csv)
        dates = session_dates(events)
        info.append("new export: %d rows, %d sessions, %s to %s"
                    % (len(rows), len(dates), dates[0], dates[-1]))
    if args.stored and not errors:
        try:
            _, old_rows = raw_rows(args.stored)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            errors.append("cannot read stored copy %s: %s" % (args.stored, exc))
            old_rows = []
        old, new = row_map(old_rows), row_map(rows)
        missing = sorted(k for k in old if k not in new)
        changed = sorted(k for k in old if k in new and old[k] != new[k])
        new_dates = sorted({k[0] for k in new} - {k[0] for k in old})
        result.update(new_sessions=new_dates, changed_rows=len(changed), missing_rows=len(missing))
        info.append("stored copy: %d rows; new sessions: %s"
                    % (len(old_rows), ", ".join(new_dates) if new_dates else "none"))
        if changed:
            info.append("%d rows changed vs stored, e.g. %s"
                        % (len(changed), "; ".join("%s %s %s" % k[:3] for k in changed[:5])))
        if missing and not args.allow_missing:
            errors.append("%d stored rows missing from the new export (data loss), e.g. %s. "
                          "Use --allow-missing if intended."
                          % (len(missing), "; ".join("%s %s %s" % k[:3] for k in missing[:5])))
        elif missing:
            info.append("%d stored rows missing from the new export (allowed)" % len(missing))
    for w in warns[:5]:
        info.append("warning: " + w)
    if not errors and args.out:
        try:
            if args.out != args.csv:
                shutil.copyfile(args.csv, args.out)
            result["wrote"] = args.out
        except OSError as exc:
            errors.append("cannot write %s: %s" % (args.out, exc))
    result["valid"] = not errors
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("VALID" if result["valid"] else "REJECTED")
        for e in errors:
            print("  error: " + e)
        for i in info:
            print("  " + i)
        if result["valid"]:
            print("  wrote %s" % args.out if result["wrote"] else "  dry run (no --out given)")
    return 0 if result["valid"] else 1


# --------------------------------------------------------------------------
# drill-down commands
# --------------------------------------------------------------------------

def cmd_session(events, args):
    names = canonical_names(events)
    dates = session_dates(events)
    target = args.date if args.date else dates[-1]
    if target not in dates:
        return die(args, "No session on %s. Nearby: %s" % (
            target, [str(d) for d in dates if abs((d - target).days) <= 7]))
    day = [e for e in events if e["date"] == target]
    result = {"date": str(target), "cycle": None, "week": None, "exercises": []}
    for d, key, st, sets in group_rows(day):
        if sets[0]["cycle"] not in (None, -1):
            result["cycle"], result["week"] = sets[0]["cycle"], sets[0]["week"]
        entry = {"name": names[key], "set_type": st or "accessory",
                 "sets": [{"reps": s["reps"], "weight": s["weight"], "completed": s["completed"]}
                          for s in sets], "notes": sets[0]["notes"]}
        if st == "Main":
            entry["top_set_e1rm"] = top_e1rm(sets)
        result["exercises"].append(entry)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    hdr = "Session: %s" % result["date"]
    if result["cycle"] is not None:
        hdr += " (Cycle %s, Week %s)" % (result["cycle"], result["week"])
    print(hdr)
    for ex in result["exercises"]:
        sets_str = " ".join("%sx%s%s" % (fmt(s["weight"]), s["reps"],
                            "" if s["completed"] else "*") for s in ex["sets"])
        line = "  %s [%s]: %s" % (ex["name"], ex["set_type"], sets_str)
        if ex.get("top_set_e1rm"):
            line += "   (top set e1RM ~%skg)" % ex["top_set_e1rm"]
        print(line)
        if ex["notes"]:
            print("    note: " + short_note(ex["notes"]))
    print("  (* = set not ticked completed)")


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


def cmd_lift(events, args):
    names = canonical_names(events)
    try:
        lift_key = resolve_lift(events, args.name)
    except ValueError as exc:
        return die(args, str(exc))
    rows, bbb_rows = [], []
    lift_groups = group_rows([e for e in events if e["key"] == lift_key])
    for d, key, st, sets in lift_groups:
        if st == "Boring but BIG sets":
            bbb_rows.append({"date": str(d), "cycle": sets[0]["cycle"], "week": sets[0]["week"],
                             "bbb": fmt_bbb(sets),
                             "volume_kg": sum((s["weight"] or 0) * (s["reps"] or 0) for s in sets)})
        if st != "Main":
            continue
        jok = next((g[3] for g in lift_groups if g[0] == d and g[2] == "Joker sets"), None)
        top = sets[-1]
        rows.append({
            "date": str(d), "cycle": sets[0]["cycle"], "week": sets[0]["week"],
            "top_set": "%sx%skg%s" % (top["reps"], fmt(top["weight"]),
                                      "" if top["completed"] is not False else " (not completed)"),
            "top_set_e1rm": top_e1rm(sets),
            "jokers": fmt_sets(jok) if jok else None,
        })
    if args.last is not None:
        rows = rows[max(0, len(rows) - args.last):]
        bbb_rows = bbb_rows[max(0, len(bbb_rows) - args.last):]
    if args.json:
        print(json.dumps({"lift": names[lift_key], "main_sessions": rows,
                          "bbb_sessions": bbb_rows}, indent=2))
        return
    print("Progression: %s" % names[lift_key])
    print("%-12s%-8s%-16s%-8s%s" % ("Date", "Cyc/Wk", "Top set", "e1RM", "Jokers"))
    for r in rows:
        cw = "%s/%s" % (r["cycle"], r["week"]) if r["cycle"] is not None else "-"
        print("%-12s%-8s%-16s%-8s%s" % (r["date"], cw, r["top_set"], fmt(r["top_set_e1rm"]),
                                        r["jokers"] or "-"))
    print("BBB for this lift (done on another lift's day):")
    for r in bbb_rows:
        cw = "%s/%s" % (r["cycle"], r["week"]) if r["cycle"] is not None else "-"
        print("  %-12s%-8s%-24s volume %.0fkg" % (r["date"], cw, r["bbb"], r["volume_kg"]))


def cmd_cycle(events, args):
    names = canonical_names(events)
    blocks = detect_blocks(events)
    if args.block is not None:
        if not 0 <= args.block < len(blocks):
            return die(args, "Block index out of range. %d blocks (0-indexed)." % len(blocks))
        block = blocks[args.block]
    else:
        block = blocks[-1]
    main_ev = [e for e in events_for_dates(events, block[2])
               if e["set_type"] == "Main" and e["cycle"] not in (None, -1)]
    if not main_ev:
        return die(args, "No main-lift cycle data in this block.")
    cycles = sorted({e["cycle"] for e in main_ev})
    target = args.cycle_num if args.cycle_num is not None else max(cycles)
    if target not in cycles:
        return die(args, "Cycle %s not in this block. Present: %s" % (target, cycles))
    by_lift = defaultdict(dict)
    for d, key, st, sets in group_rows([e for e in main_ev if e["cycle"] == target]):
        top = sets[-1]
        by_lift[key][sets[0]["week"]] = {"top_set": "%sx%skg" % (top["reps"], fmt(top["weight"])),
                                         "e1rm": top_e1rm(sets), "date": str(d)}
    result = {"block_start": str(block[0]), "cycles_in_block": cycles, "cycle": target,
              "lifts": {names[k]: v for k, v in sorted(by_lift.items())}}
    result["appears_complete"] = bool(result["lifts"]) and all(
        {1, 2, 3} <= set(v) for v in result["lifts"].values())
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print("Cycle %s (block starting %s) - %s" % (target, block[0],
          "complete (every lift has weeks 1-3)" if result["appears_complete"] else "INCOMPLETE"))
    for lift, weeks in result["lifts"].items():
        print("  %s:" % lift)
        for wk in sorted(weeks):
            w = weeks[wk]
            print("    Week %s (%s): %s  e1RM ~%skg" % (wk, w["date"], w["top_set"], fmt(w["e1rm"])))


def cmd_accessory(events, args):
    names = canonical_names(events)
    acc = [e for e in events if not e["is_main_lift_row"]]
    if args.name:
        q = norm(args.name)
        acc = [e for e in acc if q in norm(e["key"])]
    if args.since:
        acc = [e for e in acc if e["date"] >= args.since]
    rows = []
    for d, key, st, sets in group_rows(acc):
        rows.append({"date": str(d), "name": names[key], "sets": len(sets),
                     "sets_ticked": sum(1 for s in sets if s["completed"]),
                     "total_reps": sum(s["reps"] or 0 for s in sets),
                     "volume_kg": sum((s["weight"] or 0) * (s["reps"] or 0) for s in sets)})
    if args.json:
        print(json.dumps({"rows": rows}, indent=2))
        return
    print("%-12s%-30s%-6s%-8s%-6s%s" % ("Date", "Exercise", "Sets", "Ticked", "Reps", "Volume(kg)"))
    for r in rows:
        print("%-12s%-30s%-6d%-8d%-6d%.0f" % (r["date"], r["name"], r["sets"], r["sets_ticked"],
                                              r["total_reps"], r["volume_kg"]))
    print("(accessory ticks are unreliable: sets are often done but left unticked)")


def cmd_adherence(events, args):
    names = canonical_names(events)
    ev = [e for e in events if not args.since or e["date"] >= args.since]

    def rate(rows):
        known = [e for e in rows if e["completed"] is not None]
        done = sum(1 for e in known if e["completed"])
        return {"sets": len(known), "completed": done, "unknown_status": len(rows) - len(known),
                "rate": round(done / len(known), 3) if known else None}
    main = [e for e in ev if e["is_main_lift_row"]]
    acc = [e for e in ev if not e["is_main_lift_row"]]
    missed = [{"date": str(e["date"]), "exercise": names[e["key"]], "set_type": e["set_type"],
               "reps": e["reps"], "weight": e["weight"]}
              for e in main if e["completed"] is False]
    result = {"main_lifts": rate(main), "accessories": rate(acc), "main_not_completed": missed}
    if args.json:
        print(json.dumps(result, indent=2))
        return
    m = result["main_lifts"]
    print("Main-lift sets completed: %d/%d (%s)" % (m["completed"], m["sets"],
          "n/a" if m["rate"] is None else "%.1f%%" % (m["rate"] * 100)))
    a = result["accessories"]
    print("Accessory sets ticked: %d/%d (unreliable, often left unticked)" % (a["completed"], a["sets"]))
    if m["unknown_status"] or a["unknown_status"]:
        print("Sets with no completed flag (excluded): %d" % (m["unknown_status"] + a["unknown_status"]))
    if missed:
        print("Main-lift sets not completed:")
        for x in missed:
            print("  %s %s [%s] %sx%s" % (x["date"], x["exercise"], x["set_type"],
                                          fmt(x["weight"]), x["reps"]))


def cmd_list_lifts(events, args):
    variants = defaultdict(Counter)
    for e in events:
        variants[e["key"]][e["name_raw"]] += 1
    mains = set(main_lift_keys(events))
    names = canonical_names(events)
    rows = [{"name": names[k], "main_lift": k in mains, "spellings": dict(v)}
            for k, v in sorted(variants.items())]
    if args.json:
        print(json.dumps({"lifts": rows}, indent=2))
        return
    for r in rows:
        flag = " [main]" if r["main_lift"] else ""
        extra = "  spellings: %s" % ", ".join(repr(s) for s in r["spellings"]) if len(r["spellings"]) > 1 else ""
        print("%s%s%s" % (r["name"], flag, extra))


def cmd_dump(events, args):
    rows = [e for e in events if not args.date or e["date"] == args.date]
    if args.json:
        print(json.dumps({"sets": [{k: (str(v) if k == "date" else v) for k, v in e.items()
                                    if k not in ("key", "row_idx")} for e in rows]}, indent=2))
        return
    for e in rows:
        print("%s | %s | %s | #%d | %sx%s | done=%s | C%s/W%s | main=%s"
              % (e["date"], e["name_raw"], e["set_type"] or "-", e["set_index"] + 1,
                 fmt(e["weight"]), e["reps"], e["completed"], e["cycle"], e["week"],
                 e["is_main_lift_row"]))


COMMANDS = {"status": cmd_status, "summary": cmd_status, "recap": cmd_recap, "report": cmd_report,
            "session": cmd_session, "lift": cmd_lift, "cycle": cmd_cycle,
            "accessory": cmd_accessory, "adherence": cmd_adherence,
            "list-lifts": cmd_list_lifts, "dump": cmd_dump}


def build_parser():
    p = argparse.ArgumentParser(prog="five3one.py", description="Five3One CSV tool (see module docstring).")
    p.add_argument("csv", help="path to the CSV (for ingest: the NEW export)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--as-of", type=parse_date, default=None,
                        help="today's date for the user (YYYY-MM-DD); default: container date")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", aliases=["summary"], parents=[common])
    s.add_argument("--stale-days", type=int, default=3)
    s = sub.add_parser("recap", parents=[common])
    s.add_argument("--days", type=int, default=14)
    s.add_argument("--since", type=parse_date)
    s = sub.add_parser("report", parents=[common])
    s.add_argument("--out")
    s.add_argument("--stale-days", type=int, default=3)
    s = sub.add_parser("ingest", parents=[common])
    s.add_argument("--stored")
    s.add_argument("--out")
    s.add_argument("--allow-missing", action="store_true")
    s = sub.add_parser("session", parents=[common])
    s.add_argument("--date", type=parse_date)
    s = sub.add_parser("lift", parents=[common])
    s.add_argument("--name", required=True)
    s.add_argument("--last", type=int)
    s = sub.add_parser("cycle", parents=[common])
    s.add_argument("--latest", action="store_true", help="accepted for compatibility; latest is the default")
    s.add_argument("--block", type=int, help="0-indexed block number")
    s.add_argument("--cycle", dest="cycle_num", type=int)
    s = sub.add_parser("accessory", parents=[common])
    s.add_argument("--name")
    s.add_argument("--since", type=parse_date)
    s = sub.add_parser("adherence", parents=[common])
    s.add_argument("--since", type=parse_date)
    sub.add_parser("list-lifts", parents=[common])
    s = sub.add_parser("dump", parents=[common])
    s.add_argument("--date", type=parse_date)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    args = build_parser().parse_args(argv)
    args.json = as_json
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "ingest":
        return cmd_ingest(args)
    try:
        events, errors, warnings = load_events(args.csv)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return die(args, "Cannot read %s: %s" % (args.csv, exc))
    if errors:
        return die(args, "CSV problems: " + "; ".join(errors[:10]))
    if not events:
        return die(args, "No data rows in %s" % args.csv)
    for w in warnings[:5]:
        print("warning: " + w, file=sys.stderr)
    return COMMANDS[args.command](events, args) or 0


if __name__ == "__main__":
    sys.exit(main())
