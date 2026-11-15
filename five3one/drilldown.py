"""Drill-down commands: session, lift, cycle, accessory, adherence, list-lifts, dump."""

import json
from collections import Counter, defaultdict

from .model import detect_blocks, resolve_lift, top_e1rm
from .parse import (canonical_names, events_for_dates, group_rows, is_done, is_not_done,
                    main_lift_keys, session_dates)
from .text import die, fmt, fmt_bbb, fmt_sets, norm, short_note


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
                            "" if is_done(s) else "*") for s in ex["sets"])
        line = "  %s [%s]: %s" % (ex["name"], ex["set_type"], sets_str)
        if ex.get("top_set_e1rm"):
            line += "   (top set e1RM ~%skg)" % ex["top_set_e1rm"]
        print(line)
        if ex["notes"]:
            print("    note: " + short_note(ex["notes"]))
    print("  (* = set not ticked completed)")


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
                                      " (not completed)" if is_not_done(top) else ""),
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
                     "sets_ticked": sum(1 for s in sets if is_done(s)),
                     "total_reps": sum(s["reps"] or 0 for s in sets),
                     "volume_kg": sum((s["weight"] or 0) * (s["reps"] or 0) for s in sets)})
    if args.json:
        print(json.dumps({"rows": rows}, indent=2))
        return
    print("%-12s%-30s%-6s%-8s%-6s%s" % ("Date", "Exercise", "Sets", "Ticked", "Reps", "Volume(kg)"))
    for r in rows:
        print("%-12s%-30s%-6d%-8d%-6d%.0f" % (r["date"], r["name"], r["sets"], r["sets_ticked"],
                                              r["total_reps"], r["volume_kg"]))


def cmd_adherence(events, args):
    names = canonical_names(events)
    ev = [e for e in events if not args.since or e["date"] >= args.since]

    def rate(rows):
        known = [e for e in rows if e["completed"] is not None]
        done = sum(1 for e in known if is_done(e))
        return {"sets": len(known), "completed": done, "unknown_status": len(rows) - len(known),
                "rate": round(done / len(known), 3) if known else None}
    main = [e for e in ev if e["is_main_lift_row"]]
    acc = [e for e in ev if not e["is_main_lift_row"]]
    missed = [{"date": str(e["date"]), "exercise": names[e["key"]], "set_type": e["set_type"],
               "reps": e["reps"], "weight": e["weight"]}
              for e in main if is_not_done(e)]
    result = {"main_lifts": rate(main), "accessories": rate(acc), "main_not_completed": missed}
    if args.json:
        print(json.dumps(result, indent=2))
        return
    m = result["main_lifts"]
    print("Main-lift sets completed: %d/%d (%s)" % (m["completed"], m["sets"],
          "n/a" if m["rate"] is None else "%.1f%%" % (m["rate"] * 100)))
    a = result["accessories"]
    print("Accessory sets ticked: %d/%d" % (a["completed"], a["sets"]))
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
