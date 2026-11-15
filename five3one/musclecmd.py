"""Muscle commands: muscles, explain, unknowns, and the state-only commands
(map-set, map-list, param-set, param-list, feedback-add, unknown-dismiss)."""

import csv
import io
import json
from datetime import date

from . import recovery as rc
from .muscles import (LABEL, MUSCLE_IDS, UnmappedError, lens_program, lens_session, resolve_map,
                      text_program, text_session)
from .params import PARAMS, resolve_params
from .parse import session_dates
from .state import (MEASURES, StateError, add_feedback, dismiss, empty_state, load_state,
                    remove_feedback, save_state, set_mapping, set_param, summary)
from .text import die, norm


def unmapped_error(args, exc):
    path = getattr(args, "state", None) or "STATE.json"
    fixes = exc.fixes(path)
    if getattr(args, "json", False):
        print(json.dumps({"error": str(exc), "unmapped": exc.names, "fix": fixes}))
    else:
        import sys
        print("Muscle output withheld: %s.\nMap each one, then rerun:\n  %s"
              % (exc, "\n  ".join(fixes)), file=sys.stderr)
    return 1


def build_all(events, state, as_of, weeks=4, notes_since=None, state_path="STATE.json"):
    """All three lenses plus unknowns, from one export. Raises UnmappedError."""
    emap = resolve_map(state)
    params = resolve_params(state)
    last = session_dates(events)[-1]
    as_of = max(as_of or last, last)
    return {
        "as_of": str(as_of), "last_session": str(last),
        "program": lens_program(events, emap, None, weeks),
        "session": lens_session(events, emap),
        "recovery": rc.lens_recovery(events, emap, params, state, as_of),
        "unknowns": rc.unknowns(events, emap, params, state, as_of, notes_since, state_path),
        "state": {"revision": state["revision"] if state else None, "summary": summary(state)},
    }


MUSCLE_CSV_COLUMNS = ["muscle", "sets_per_week", "direct_sets_per_week", "days_per_week",
                      "last_hit", "dose", "not_before", "recovered_by"]


def muscle_csv(allres):
    """The stored muscle file. Dates, not states, so it does not go stale as days pass."""
    prog = {m["muscle"]: m for m in allres["program"]["muscles"]}
    w = allres["program"]["window"]
    buf = io.StringIO()
    buf.write("# five3one muscle file. Overwritten on each export; do not edit by hand.\n")
    buf.write("# last_session=%s generated_as_of=%s program_window=%s..%s state_revision=%s k=%g\n"
              % (allres["last_session"], allres["as_of"], w["start"], w["end"],
                 "none" if allres["state"]["revision"] is None else allres["state"]["revision"],
                 allres["recovery"]["k"]))
    buf.write("# Reading a row on date D: D < not_before = likely not recovered; "
              "D < recovered_by = uncertain; otherwise likely recovered, or 'not trained recently' "
              "once last_hit is more than 14 days before D. Blank = no done work in the export.\n")
    buf.write("# Valid only while last_session above is still the last logged session. "
              "sets_per_week counts secondary work at half; direct = primary-mover sets.\n")
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(MUSCLE_CSV_COLUMNS)
    for m in allres["recovery"]["muscles"]:
        p = prog[m["muscle"]]
        wr.writerow([m["muscle"], p["sets_per_week"], p["direct_sets_per_week"], p["days_per_week"],
                     m["last_hit"] or "", "" if m["dose"] is None else m["dose"],
                     m["not_before"] or "", m["recovered_by"] or ""])
    return buf.getvalue()


def _state_or_die(args):
    try:
        return load_state(getattr(args, "state", None)), None
    except StateError as exc:
        return None, die(args, str(exc))


def cmd_muscles(events, args):
    state, err = _state_or_die(args)
    if err:
        return err
    try:
        emap = resolve_map(state)
        if args.lens == "program":
            res = lens_program(events, emap, args.as_of, args.weeks)
            text = text_program(res)
        elif args.lens == "session":
            res = lens_session(events, emap, args.date)
            text = text_session(res)
        else:
            res = rc.lens_recovery(events, emap, resolve_params(state), state, args.as_of)
            text = rc.text_recovery(res)
        if args.html:
            from .render import render_html
            last = session_dates(events)[-1]
            allres = build_all(events, state, args.as_of or last, args.weeks,
                               state_path=args.state or "STATE.json")
            with open(args.html, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(render_html(allres))
    except UnmappedError as exc:
        return unmapped_error(args, exc)
    except (ValueError, OSError) as exc:
        return die(args, str(exc))
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(text)
        if args.html:
            print("wrote %s" % args.html)


def cmd_explain(events, args):
    """The sets, parameters and feedback behind one muscle's figures."""
    state, err = _state_or_die(args)
    if err:
        return err
    if args.muscle not in MUSCLE_IDS:
        return die(args, "unknown muscle %r. Muscles: %s" % (args.muscle, ", ".join(MUSCLE_IDS)))
    try:
        emap, params = resolve_map(state), resolve_params(state)
        last = session_dates(events)[-1]
        rec = rc.lens_recovery(events, emap, params, state, max(args.as_of or last, last))
        prog = lens_program(events, emap, None, args.weeks)
    except UnmappedError as exc:
        return unmapped_error(args, exc)
    except ValueError as exc:
        return die(args, str(exc))
    r = next(m for m in rec["muscles"] if m["muscle"] == args.muscle)
    p = next(m for m in prog["muscles"] if m["muscle"] == args.muscle)
    used = sorted({s["stimulus_param"] for s in r["sets"]})
    band = r["band"]
    pnames = used + ([band + ".lo", band + ".hi"] if band else []) + ["k", "mult." + args.muscle]
    fb = [f for f in ((state or {}).get("feedback") or [])
          if f["scope"] == args.muscle or (f["scope"] == "all" and f["measure"] == "limited")]
    res = {"muscle": args.muscle, "as_of": rec["as_of"], "recovery": r, "program": p,
           "program_window": prog["window"],
           "parameters": {n: {"value": params[n], "default": PARAMS[n]["default"],
                              "basis": PARAMS[n]["basis"]} for n in pnames},
           "feedback": fb}
    if args.json:
        print(json.dumps(res, indent=2))
        return
    print("%s as of %s" % (LABEL[args.muscle], rec["as_of"]))
    if r["last_hit"] is None:
        print("  Recovery: not trained in this export.")
    else:
        print("  Recovery: %s. Last hit %s (dose %g). Window from the %s session (%s): "
              "not before %s, recovered by %s."
              % (r["state"], r["last_hit"], r["dose"], r["window_from_session"], band,
                 r["not_before"], r["recovered_by"]))
        print("  Sets behind that window (set, kind, muscle weight x stimulus = dose):")
        for s in r["sets"]:
            print("    %-26s %-9s %-10s %g x %g (%s) = %g"
                  % (s["exercise"], s["set"], s["kind"], s["muscle_weight"], s["stimulus"],
                     s["stimulus_param"], s["dose"]))
    print("  Program (%s to %s): %.1f sets/week, %.1f direct, %.1f days/week"
          % (prog["window"]["start"], prog["window"]["end"], p["sets_per_week"],
             p["direct_sets_per_week"], p["days_per_week"]))
    for e in p["exercises"]:
        print("    %-26s %d sets at muscle weight %g" % (e["name"], e["sets"], e["muscle_weight"]))
    print("  Parameters used:")
    for n in pnames:
        v = res["parameters"][n]
        tag = "" if v["value"] == v["default"] else " (default %g)" % v["default"]
        print("    %-22s %g%s  [%s]" % (n, v["value"], tag, v["basis"]))
    if fb:
        print("  Feedback:")
        for f in fb:
            print("    %s %s %s = %d (%s)" % (f["about_date"], f["measure"], f["scope"],
                                             f["value"], f["source"]))


def cmd_unknowns(events, args):
    state, err = _state_or_die(args)
    if err:
        return err
    try:
        last = session_dates(events)[-1]
        items = rc.unknowns(events, resolve_map(state), resolve_params(state), state,
                            max(args.as_of or last, last), args.notes_since,
                            args.state or "STATE.json")
    except UnmappedError as exc:
        return unmapped_error(args, exc)
    except ValueError as exc:
        return die(args, str(exc))
    if args.json:
        print(json.dumps({"unknowns": items}, indent=2))
    else:
        print(rc.text_unknowns(items))


# ---------------------------------------------------------------------------
# State-only commands (no CSV)
# ---------------------------------------------------------------------------

def _open_state(args):
    st = load_state(args.state)
    return st if st is not None else empty_state()


def _saved(args, state, changed, payload, line):
    if changed:
        try:
            payload["revision"] = save_state(args.state, state)
        except StateError as exc:
            return die(args, str(exc))
    else:
        payload["revision"] = state["revision"]
    payload["changed"] = changed
    if args.json:
        print(json.dumps(payload, indent=2))
    elif changed:
        print("%s (state revision %d). Save the state file back to the project."
              % (line, payload["revision"]))
    else:
        print("%s - no change (state revision %d)." % (line, payload["revision"]))
    return 0


def cmd_map_set(args):
    try:
        weights = {}
        for item in args.weights:
            if "=" not in item:
                raise StateError("expected MUSCLE=1 or MUSCLE=0.5, got %r" % item)
            m, w = item.split("=", 1)
            weights[m.strip()] = float(w)
        state = _open_state(args)
        changed = set_mapping(state, args.exercise, weights)
    except (StateError, ValueError) as exc:
        return die(args, str(exc))
    return _saved(args, state, changed, {"exercise": args.exercise, "weights": weights},
                  "mapped %s -> %s" % (args.exercise, ", ".join(
                      "%s=%g" % kv for kv in weights.items())))


def cmd_map_list(args):
    try:
        state = load_state(args.state)
    except StateError as exc:
        return die(args, str(exc))
    from .muscles import DEFAULT_MAP
    over = {norm(k): (k, v) for k, v in ((state or {}).get("exercise_map") or {}).items()}
    rows = [{"exercise": k, "weights": v, "source": "default"}
            for k, v in sorted(DEFAULT_MAP.items()) if k not in over]
    rows += [{"exercise": name, "weights": v, "source": "state"} for name, v in over.values()]
    if args.json:
        print(json.dumps({"map": rows}, indent=2))
        return 0
    for r in rows:
        print("%-28s %-8s %s" % (r["exercise"], r["source"],
                                 ", ".join("%s=%g" % kv for kv in r["weights"].items())))
    return 0


def cmd_param_set(args):
    try:
        state = _open_state(args)
        changed, old, new = set_param(state, args.name, args.value, args.reason,
                                      str(args.as_of or date.today()))
    except (StateError, ValueError) as exc:
        return die(args, str(exc))
    return _saved(args, state, changed, {"param": args.name, "old": old, "new": new},
                  "%s: %g -> %g" % (args.name, old, new))


def cmd_param_list(args):
    try:
        state = load_state(args.state)
        values = resolve_params(state)
    except (StateError, ValueError) as exc:
        return die(args, str(exc))
    rows = [{"name": n, "value": values[n], "default": p["default"], "min": p["min"],
             "max": p["max"], "basis": p["basis"], "note": p["note"]}
            for n, p in PARAMS.items()
            if args.all or not n.startswith("mult.") or values[n] != p["default"]]
    log = (state or {}).get("param_log") or []
    if args.json:
        print(json.dumps({"params": rows, "log": log}, indent=2))
        return 0
    print("%-16s%8s%9s%14s  %-18s%s" % ("Parameter", "Value", "Default", "Range", "Basis", "Note"))
    for r in rows:
        print("%-16s%8g%9g%14s  %-18s%s" % (r["name"], r["value"], r["default"],
                                            "%g to %g" % (r["min"], r["max"]), r["basis"], r["note"]))
    if not args.all:
        print("(mult.<muscle> multipliers at their default of 1 are hidden; --all shows them)")
    for entry in log:
        print("changed %s: %s %g -> %g (%s)" % (entry["date"], entry["param"], entry["old"],
                                               entry["new"], entry["reason"]))
    return 0


def cmd_feedback_add(args):
    try:
        state = _open_state(args)
        changed, entry = add_feedback(state, args.measure, str(args.about_date), args.scope,
                                      args.value, str(args.as_of or date.today()),
                                      args.source, args.quote)
    except StateError as exc:
        return die(args, str(exc))
    return _saved(args, state, changed, {"feedback": entry},
                  "recorded %s %s %s = %d" % (entry["about_date"], entry["measure"],
                                              entry["scope"], entry["value"]))


def cmd_feedback_remove(args):
    try:
        state = _open_state(args)
        remove_feedback(state, args.id)
    except StateError as exc:
        return die(args, str(exc))
    return _saved(args, state, True, {"removed": args.id}, "removed feedback %s" % args.id)


def cmd_unknown_dismiss(args):
    try:
        state = _open_state(args)
        changed = dismiss(state, args.id)
    except StateError as exc:
        return die(args, str(exc))
    return _saved(args, state, changed, {"dismissed": args.id}, "dismissed %s" % args.id)


STATE_COMMANDS = {"map-set": cmd_map_set, "map-list": cmd_map_list, "param-set": cmd_param_set,
                  "param-list": cmd_param_list, "feedback-add": cmd_feedback_add,
                  "feedback-remove": cmd_feedback_remove,
                  "unknown-dismiss": cmd_unknown_dismiss}
MEASURE_HELP = "; ".join("%s = %s" % (k, v[3]) for k, v in MEASURES.items())
