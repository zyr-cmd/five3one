"""ingest: validate a new export and compare it with a stored copy."""

import csv
import json
import shutil
from collections import Counter

from .parse import cell, load_events, raw_rows, session_dates
from .text import die


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
