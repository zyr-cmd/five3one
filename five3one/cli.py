"""Argument parsing and dispatch."""

import argparse
import csv
import sys

from .drilldown import (cmd_accessory, cmd_adherence, cmd_cycle, cmd_dump, cmd_lift,
                        cmd_list_lifts, cmd_session)
from .ingest import cmd_ingest
from .parse import load_events, parse_date
from .report import cmd_recap, cmd_report, cmd_status, cmd_update
from .text import die


COMMANDS = {"status": cmd_status, "summary": cmd_status, "recap": cmd_recap, "report": cmd_report,
            "session": cmd_session, "lift": cmd_lift, "cycle": cmd_cycle,
            "accessory": cmd_accessory, "adherence": cmd_adherence,
            "list-lifts": cmd_list_lifts, "dump": cmd_dump}


def build_parser():
    p = argparse.ArgumentParser(prog="five3one", description="Five3One CSV tool (see package docstring).")
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
    s = sub.add_parser("update", parents=[common])
    s.add_argument("--out-dir", required=True)
    s.add_argument("--min-sessions", type=int)
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
    if args.command == "update":
        return cmd_update(args)
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
