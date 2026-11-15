"""status, recap, report and update (the agent entry points)."""

import argparse
import contextlib
import csv
import io
import json
import shutil
from datetime import date, timedelta

from .model import derive_training_maxes, detect_blocks, e1rm_history, top_e1rm
from .parse import (canonical_names, events_for_dates, group_rows, is_done, is_not_done,
                    load_events, main_lift_keys, session_dates)
from .text import die, fmt, fmt_bbb, fmt_sets, short_note


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
            bad = [s for s in sets if is_not_done(s)]
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
                t = sum(1 for s in sets if is_done(s))
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


REPORT_HEADER = ("# Progress\n\nGenerated by five3one.py from workouts.csv (last logged session %s), "
                 "as of %s local date. Pure script output: overwrite whole on each export. "
                 "Hand-written plans live in weightlifting.md. If he has trained since, ask for a "
                 "fresh export and regenerate (see log-update.md).\n")


def _capture(fn, events, ns):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(events, ns)
    return buf.getvalue()


def next_session_section(events, as_of, state=None, state_path="STATE.json"):
    """(markdown section, build_all result or None). One line; the full table is the muscle file."""
    from .musclecmd import build_all
    from .muscles import UnmappedError
    from .recovery import text_next
    try:
        allres = build_all(events, state, as_of, state_path=state_path)
    except UnmappedError as exc:
        return ("\n## Next session\nMuscle output withheld: %s. Map each one "
                "(map-set), then rerun.\n" % exc), None
    return ("\n## Next session\n%s\nPer-muscle figures: muscles.csv. %s\n"
            % (text_next(allres["recovery"]["next_session"]), allres["state"]["summary"])), allres


def build_report(events, as_of, stale_days=3, recap_days=14, state=None):
    today = as_of or date.today()
    status = _capture(cmd_status, events, argparse.Namespace(
        as_of=today, stale_days=stale_days, json=False))
    recap = _capture(cmd_recap, events, argparse.Namespace(
        as_of=today, days=recap_days, since=None, json=False))
    return (REPORT_HEADER % (session_dates(events)[-1], today)
            + "\n## Status\n```\n" + status + "```\n"
            + "\n## Recap (%d days before last session)\n```\n" % recap_days + recap + "```\n"
            + next_session_section(events, today, state)[0])


def cmd_report(events, args):
    from .state import StateError, load_state
    try:
        state = load_state(getattr(args, "state", None))
    except StateError as exc:
        return die(args, str(exc))
    text = build_report(events, args.as_of, args.stale_days, state=state)
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


def cmd_update(args):
    """Validate a new export, refuse if it has fewer sessions than expected,
    then write OUT_DIR/workouts.csv and OUT_DIR/progress.md."""
    import os
    try:
        events, errors, warns = load_events(args.csv)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return die(args, "REJECTED: cannot read %s: %s" % (args.csv, exc))
    if errors:
        return die(args, "REJECTED: " + "; ".join(errors[:10]))
    if not events:
        return die(args, "REJECTED: no data rows in %s" % args.csv)
    from .state import StateError, load_state
    try:
        state = load_state(args.state)
    except StateError as exc:
        return die(args, "REJECTED: %s" % exc)
    if args.state_revision is not None:
        have = state["revision"] if state else None
        if have is None or have < args.state_revision:
            return die(args, "REJECTED: the stored muscle file expects state revision %d but %s. "
                             "The state file is missing or older than the one last used "
                             "(mappings, tuning and feedback would be lost). Find the current "
                             "state file, or ask before continuing."
                       % (args.state_revision, "no state file was given or found" if have is None
                          else "the state file is at revision %d" % have))
    n = len(session_dates(events))
    if args.min_sessions is not None and n < args.min_sessions:
        return die(args, "REJECTED: export has %d sessions, expected at least %d "
                         "(possible data loss). Ask before continuing." % (n, args.min_sessions))
    os.makedirs(args.out_dir, exist_ok=True)
    csv_out = os.path.join(args.out_dir, "workouts.csv")
    md_out = os.path.join(args.out_dir, "progress.md")
    mcsv_out = os.path.join(args.out_dir, "muscles.csv")
    html_out = os.path.join(args.out_dir, "muscles.html")
    today = args.as_of or date.today()
    _, allres = next_session_section(events, today, state, args.state or "STATE.json")
    if allres is not None and args.notes_since:
        from . import recovery as rc
        from .muscles import resolve_map
        from .params import resolve_params
        allres["unknowns"] = rc.unknowns(events, resolve_map(state), resolve_params(state), state,
                                         max(today, session_dates(events)[-1]), args.notes_since,
                                         args.state or "STATE.json")
    try:
        if os.path.abspath(args.csv) != os.path.abspath(csv_out):
            shutil.copyfile(args.csv, csv_out)
        with open(md_out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(build_report(events, args.as_of, state=state))
        wrote_muscles = []
        if allres is not None:
            from .musclecmd import muscle_csv
            from .render import render_html
            with open(mcsv_out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(muscle_csv(allres))
            with open(html_out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(render_html(allres))
            wrote_muscles = [mcsv_out, html_out]
    except OSError as exc:
        return die(args, "cannot write output: %s" % exc)
    dates = session_dates(events)
    result = {"valid": True, "sessions": n, "first": str(dates[0]), "last": str(dates[-1]),
              "wrote": [csv_out, md_out] + wrote_muscles, "warnings": warns[:5]}
    from .muscles import UnmappedError, resolve_map, counted_sets
    from .recovery import text_next, text_unknowns
    if allres is None:
        try:
            counted_sets(events, resolve_map(state))
        except UnmappedError as exc:
            result["muscles"] = {"withheld": True, "unmapped": exc.names,
                                 "fix": exc.fixes(args.state or "STATE.json")}
    else:
        result["muscles"] = {"withheld": False, "next_session": allres["recovery"]["next_session"],
                             "state": allres["state"], "unknowns": allres["unknowns"]}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("VALID: %d sessions, %s to %s" % (n, dates[0], dates[-1]))
        for w in warns[:5]:
            print("  warning: " + w)
        for path in result["wrote"]:
            print("  wrote %s" % path)
        if allres is None:
            m = result["muscles"]
            print("MUSCLE OUTPUT WITHHELD: no muscle mapping for %s.\nMap each one, then rerun:\n  %s"
                  % (", ".join(m["unmapped"]), "\n  ".join(m["fix"])))
        else:
            print(text_next(allres["recovery"]["next_session"]))
            print(allres["state"]["summary"])
            print(text_unknowns(allres["unknowns"]))
    return 0
