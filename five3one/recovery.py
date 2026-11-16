"""Lens C (recovery), the next-session line, the prediction tally and the unknowns.

Model, in whole days (the export has dates only):
  dose(muscle, date) = sum over done sets that day of stimulus weight x muscle weight
  window(dose)       = [lo, hi] days from the dose bands, times k times mult.<muscle>,
                       rounded up to whole days
  state on a date    = likely not recovered  before  hit + lo
                       uncertain             before  hit + hi
                       likely recovered      from    hit + hi
                       not trained recently  when the last hit is over 14 days back
When several sessions hit a muscle, the latest window ends win; doses on different
days are not summed. Within one session everything that trains the muscle is summed.
"Recovered" means performance capacity, not absence of soreness. This is a heuristic:
the windows are literature ranges (see params.py and docs/SOURCES.md), not measurements
of this person; k and mult.* are the personal adjustments.
"""

import math
from collections import defaultdict
from datetime import timedelta

from .model import detect_blocks
from .muscles import LABEL, MUSCLE_IDS, counted_sets
from .parse import canonical_names, events_for_dates, group_rows, is_done, session_dates
from .text import norm, short_note

NOT, UNCERTAIN, RECOVERED, UNTRAINED = ("likely not recovered", "uncertain",
                                        "likely recovered", "not trained recently")
RECENT_HIT_DAYS = 14  # a muscle last hit longer ago than this is "not trained recently"
RECENT_DAYS = 3  # questions about a session are only worth asking this soon after it


def _rir_lookup(state):
    return {(f["about_date"], norm(f["scope"])): f["value"]
            for f in ((state or {}).get("feedback") or []) if f["measure"] == "rir"}


RIR_KINDS = ("joker", "bbb", "accessory")  # the kinds an effort question covers


def shortfalls(rows):
    """{(date, norm(key)): sets} for joker, BBB and accessory work in which a done set fell
    short of the reps of an earlier done set at the same or a heavier weight that session
    (e.g. 70x12 70x12 70x10). That is read as at or near failure, so it is not asked about."""
    groups = defaultdict(list)
    for r in rows:
        if r["kind"] in RIR_KINDS:
            groups[(str(r["date"]), norm(r["key"]))].append(r)
    out = {}
    for k, sets in groups.items():
        sets = sorted(sets, key=lambda r: r["order"])
        for i, r in enumerate(sets):
            if any(e["weight"] >= r["weight"] and int(e["reps"]) > int(r["reps"]) for e in sets[:i]):
                out[k] = " ".join("%gx%s" % (x["weight"], x["reps"]) for x in sets)
                break
    return out


def set_stimulus(row, params, rir_by, short=None):
    """(stimulus weight, parameter used, effort source). Stated reps in reserve beat a rep
    shortfall, which beats the set kind, for joker, BBB and accessory sets; main work sets
    and the top set keep their own weights."""
    key = (str(row["date"]), norm(row["key"]))
    rir = rir_by.get(key) if row["kind"] in RIR_KINDS else None
    if rir is not None:
        name = "rir.0_1" if rir <= 1 else "rir.2_3" if rir <= 3 else "rir.4_plus"
        return params[name], name, "stated"
    if row["kind"] in RIR_KINDS and short and key in short:
        return params["rir.0_1"], "rir.0_1", "inferred: reps fell short"
    name = "stim.main_top" if row["top"] else "stim." + row["kind"]
    return params[name], name, None


def daily_doses(rows, params, state=None):
    """{muscle: {date: {"dose": x, "sets": [detail...]}}}"""
    rir_by = _rir_lookup(state)
    short = shortfalls(rows)
    out = {m: {} for m in MUSCLE_IDS}
    for r in rows:
        stim, pname, source = set_stimulus(r, params, rir_by, short)
        for m, w in r["muscles"].items():
            day = out[m].setdefault(r["date"], {"dose": 0.0, "sets": []})
            day["dose"] += stim * w
            day["sets"].append({"exercise": r["name"], "kind": "main_top" if r["top"] else r["kind"],
                                "set": "%gx%s" % (r["weight"], r["reps"]), "muscle_weight": w,
                                "stimulus": stim, "stimulus_param": pname, "effort": source,
                                "dose": round(stim * w, 3)})
    return out


def window_days(dose, params, muscle):
    """(lo_days, hi_days, band) as whole days after the hit."""
    band = "band5"
    for name in ("band1", "band2", "band3", "band4"):
        if dose <= params[name + ".upto"]:
            band = name
            break
    scale = params["k"] * params["mult." + muscle]
    lo = int(math.ceil(params[band + ".lo"] * scale - 1e-9))
    hi = int(math.ceil(params[band + ".hi"] * scale - 1e-9))
    return lo, max(hi, lo), band


def muscle_status(days, params, muscle, on, strictly_before=False):
    """State of one muscle on date `on` from its {date: {dose, sets}} history.
    strictly_before=True ignores a hit on `on` itself (the state going into that session)."""
    hits = [(d, v) for d, v in days.items() if (d < on if strictly_before else d <= on)]
    if not hits:
        return {"state": UNTRAINED, "last_hit": None, "dose": None, "not_before": None,
                "recovered_by": None, "governing_date": None, "window_dose": None,
                "band": None, "sets": []}
    last = max(d for d, _ in hits)
    not_before = recovered_by = gov = None
    gov_band = None
    for d, v in hits:
        lo, hi, band = window_days(v["dose"], params, muscle)
        nb, rb = d + timedelta(days=lo), d + timedelta(days=hi)
        if not_before is None or nb > not_before:
            not_before = nb
        if recovered_by is None or rb > recovered_by or (rb == recovered_by and d > gov):
            recovered_by, gov, gov_band = rb, d, band
    if (on - last).days > RECENT_HIT_DAYS and on >= recovered_by:
        state = UNTRAINED
    else:
        state = NOT if on < not_before else UNCERTAIN if on < recovered_by else RECOVERED
    return {"state": state, "last_hit": last, "dose": round(days[last]["dose"], 2),
            "not_before": not_before, "recovered_by": recovered_by, "governing_date": gov,
            "window_dose": round(days[gov]["dose"], 2), "band": gov_band,
            "sets": days[gov]["sets"]}


def lens_recovery(events, emap, params, state, as_of):
    last_session = session_dates(events)[-1]
    if as_of is None:
        raise ValueError("the recovery lens needs --as-of with the owner's local date")
    if as_of < last_session:
        raise ValueError("--as-of %s is before the last logged session %s" % (as_of, last_session))
    rows, other = counted_sets(events, emap)
    doses = daily_doses(rows, params, state)
    from .params import PARAMS
    overrides = {n for n, v in ((state or {}).get("params") or {}).items()
                 if v != PARAMS[n]["default"]}
    muscles = []
    for m in MUSCLE_IDS:
        st = muscle_status(doses[m], params, m, as_of)
        muscles.append({
            "muscle": m, "label": LABEL[m], "state": st["state"],
            "last_hit": str(st["last_hit"]) if st["last_hit"] else None,
            "days_since": (as_of - st["last_hit"]).days if st["last_hit"] else None,
            "dose": st["dose"],
            "not_before": str(st["not_before"]) if st["not_before"] else None,
            "recovered_by": str(st["recovered_by"]) if st["recovered_by"] else None,
            "window_from_session": str(st["governing_date"]) if st["governing_date"] else None,
            "window_dose": st["window_dose"], "band": st["band"], "multiplier": params["k"] * params["mult." + m],
            "tuning": "adjusted" if ({"k", "mult." + m} & overrides) else "default",
            "sets": st["sets"]})
    res = {"lens": "recovery", "as_of": str(as_of), "last_session": str(last_session),
           "k": params["k"], "muscles": muscles, "uncounted_other_sets": other,
           "next_session": next_session(events, emap, doses, params, last_session),
           "tally": prediction_tally(rows, doses, params, state),
           "unmatched_feedback": unmatched_feedback(rows, state)}
    return res


def unmatched_feedback(rows, state):
    """Feedback entries that match no done work in this export (wrong date or a misspelt
    exercise). They are stored but have no effect; the agent should correct them."""
    days = defaultdict(set)
    for r in rows:
        days[str(r["date"])].add(norm(r["key"]))
    out = []
    for f in ((state or {}).get("feedback") or []):
        if f["about_date"] not in days:
            out.append({"id": f["id"], "why": "no done sets on %s" % f["about_date"]})
        elif f["measure"] == "rir" and norm(f["scope"]) not in days[f["about_date"]]:
            out.append({"id": f["id"], "why": "no done sets of %r on %s" % (f["scope"], f["about_date"])})
    return out


def next_main_lift(events):
    """(key, why) for the next main lift: the one longest since trained among those
    remaining this week; if the week is complete, the lift that opened it."""
    blk = detect_blocks(events)[-1]
    blk_events = events_for_dates(events, blk[2])
    main_rows = [e for e in blk_events if e["set_type"] == "Main" and e["cycle"] not in (None, -1)
                 and is_done(e)]
    if not main_rows:
        return None, "no done main-lift sets in the current block"
    latest = max(main_rows, key=lambda e: (e["date"], e["row_idx"]))
    cycle, week = latest["cycle"], latest["week"]
    done, last_main = {}, {}
    for e in main_rows:
        last_main[e["key"]] = max(last_main.get(e["key"], e["date"]), e["date"])
        if e["cycle"] == cycle and e["week"] == week:
            done[e["key"]] = min(done.get(e["key"], e["date"]), e["date"])
    remaining = sorted((k for k in last_main if k not in done), key=lambda k: last_main[k])
    if remaining:
        return remaining[0], "not yet done in cycle %s week %s" % (cycle, week)
    opener = min(done, key=lambda k: done[k])
    return opener, "cycle %s week %s is complete; this lift opened it" % (cycle, week)


def next_session(events, emap, doses, params, last_session):
    names = canonical_names(events)
    key, why = next_main_lift(events)
    if key is None:
        return {"available": False, "why": why}
    # companion BBB lift: from the most recent session where this lift had done Main sets
    companion = None
    main_dates = sorted({e["date"] for e in events
                         if e["key"] == key and e["set_type"] == "Main" and is_done(e)})
    if main_dates:
        d = main_dates[-1]
        for _, k, st, sets in group_rows([e for e in events if e["date"] == d]):
            if st == "Boring but BIG sets" and any(is_done(s) for s in sets):
                companion = k
    lifts = [k for k in (key, companion) if k]
    no_map = [names[k] for k in lifts if norm(k) not in emap]
    if no_map:
        return {"available": False,
                "why": "next is %s, but no muscle mapping for %s (map-set it)"
                       % (names[key], ", ".join(no_map))}
    need = []
    for k in lifts:
        for m, w in (emap.get(norm(k)) or {}).items():
            if w >= 1.0 and m not in need:
                need.append(m)
    per = []
    for m in need:
        st = muscle_status(doses[m], params, m, last_session)
        per.append({"muscle": m, "label": LABEL[m],
                    "not_before": str(st["not_before"]) if st["not_before"] else None,
                    "recovered_by": str(st["recovered_by"]) if st["recovered_by"] else None})
    nbs = [p["not_before"] for p in per if p["not_before"]]
    rbs = [p["recovered_by"] for p in per if p["recovered_by"]]
    return {"available": True, "main_lift": names[key], "why": why,
            "bbb_lift": names[companion] if companion else None,
            "muscles": per,
            "earliest": max(nbs) if nbs else None,
            "all_likely_recovered": max(rbs) if rbs else None,
            "valid_while_last_session_is": str(last_session)}


def text_next(ns):
    if not ns or not ns.get("available"):
        return "Next session: not available (%s)." % (ns or {}).get("why", "no data")
    lift = ns["main_lift"] + (" + %s BBB" % ns["bbb_lift"] if ns["bbb_lift"] else "")
    if not ns["earliest"]:
        return ("Next session: %s. No done work is recorded for its primary muscles (%s), so "
                "recovery puts no constraint on it." % (lift, ", ".join(p["label"] for p in ns["muscles"])))
    limiting = [p["label"] for p in ns["muscles"] if p["recovered_by"] == ns["all_likely_recovered"]]
    return ("Next session: %s. Its primary muscles (%s) are past 'likely not recovered' from %s "
            "and all likely recovered from %s (last to clear: %s). Valid only while %s is the "
            "last logged session."
            % (lift, ", ".join(p["label"] for p in ns["muscles"]), ns["earliest"],
               ns["all_likely_recovered"], ", ".join(limiting), ns["valid_while_last_session_is"]))


def prediction_tally(rows, doses, params, state):
    """How the model's state going into a session compared with what the owner reported.
    {state: {"limited": n, "not_limited": n}} plus the points behind it."""
    fb = [f for f in ((state or {}).get("feedback") or []) if f["measure"] == "limited"]
    table = {s: {"limited": 0, "not_limited": 0} for s in (NOT, UNCERTAIN, RECOVERED, UNTRAINED)}
    points = []
    by_date = defaultdict(list)
    for r in rows:
        by_date[str(r["date"])].append(r)
    named = {(f["about_date"], f["scope"]) for f in fb if f["scope"] != "all"}
    for f in fb:
        day_rows = by_date.get(f["about_date"])
        if not day_rows:
            continue
        on = day_rows[0]["date"]
        if f["scope"] == "all":
            muscles = []
            for r in day_rows:
                if r["kind"] in ("main", "joker", "bbb"):
                    for m, w in r["muscles"].items():
                        if w >= 1.0 and m not in muscles and (f["about_date"], m) not in named:
                            muscles.append(m)
        else:
            muscles = [f["scope"]]
        for m in muscles:
            st = muscle_status(doses[m], params, m, on, strictly_before=True)["state"]
            col = "limited" if f["value"] >= 1 else "not_limited"
            table[st][col] += 1
            points.append({"date": f["about_date"], "muscle": m, "predicted": st,
                           "reported": f["value"]})
    return {"points": len(points), "table": table, "detail": points}


def text_recovery(res):
    t = res["tally"]
    out = ["Recovery as of %s (last session %s; k = %g; %d feedback point%s on limited performance)"
           % (res["as_of"], res["last_session"], res["k"], t["points"], "" if t["points"] == 1 else "s"),
           text_next(res["next_session"]),
           "%-18s%-12s%6s  %-12s%-13s%s" % ("Muscle", "Last hit", "Dose", "Not before",
                                            "Recovered by", "State")]
    order = {NOT: 0, UNCERTAIN: 1, RECOVERED: 2, UNTRAINED: 3}
    for m in sorted(res["muscles"], key=lambda x: (order[x["state"]], x["recovered_by"] or "", x["label"]),
                    reverse=False):
        out.append("%-18s%-12s%6s  %-12s%-13s%s%s" % (
            m["label"], m["last_hit"] or "-", "-" if m["dose"] is None else "%g" % m["dose"],
            m["not_before"] or "-", m["recovered_by"] or "-", m["state"],
            "" if m["tuning"] == "default" else " (window adjusted x%g)" % m["multiplier"]))
    if t["points"]:
        out.append("Predictions vs reports (state going into the session: limited / not limited):")
        for s in (RECOVERED, UNCERTAIN, NOT, UNTRAINED):
            out.append("  %-22s %d / %d" % (s, t["table"][s]["limited"], t["table"][s]["not_limited"]))
    for u in res.get("unmatched_feedback") or []:
        out.append("WARNING: feedback %s matches nothing in this export (%s); it has no effect. "
                   "Remove it (feedback-remove) and record it again correctly." % (u["id"], u["why"]))
    out.append("Heuristic: windows are literature ranges, not measurements of this person.")
    return "\n".join(out)


def unknowns(events, emap, params, state, as_of, notes_since=None, state_path="STATE.json"):
    """What the tool does not know about recent sessions, ranked, each with what the
    answer would change and the command that records it. The agent decides what to ask."""
    st = state or {}
    closed = set(st.get("answered") or []) | set(st.get("dismissed") or [])
    names = canonical_names(events)
    dates = session_dates(events)
    latest = dates[-1]
    rows, _ = counted_sets(events, emap)
    doses = daily_doses(rows, params, state)
    out = []

    note_dates = [d for d in dates if d > notes_since] if notes_since else [latest]
    seen = set()
    for e in events:
        if e["date"] in note_dates and e["notes"] and e["set_index"] == 0:
            uid = "note:%s:%s%s" % (e["date"], norm(e["key"]),
                                    ":" + norm(e["set_type"]) if e["set_type"] else "")
            if uid in closed or uid in seen:
                continue
            seen.add(uid)
            out.append({"id": uid, "type": "note", "about_date": str(e["date"]),
                        "exercise": names[e["key"]], "text": short_note(e["notes"], 400),
                        "what_to_do": "Read it. If it states how hard a lift was or that a muscle "
                                      "limited a lift, record that with feedback-add (--source note "
                                      "--quote). Then dismiss it.",
                        "record": "unknown-dismiss --state %s %s" % (state_path, uid)})

    recent = as_of is not None and 0 <= (as_of - latest).days <= RECENT_DAYS
    if recent:
        uid = "limited:%s" % latest
        used = []
        for r in rows:
            if r["date"] == latest and r["kind"] in ("main", "joker", "bbb"):
                for m, w in r["muscles"].items():
                    if w >= 1.0 and m not in used:
                        used.append(m)
        if uid not in closed and used:
            pred = [{"muscle": m, "predicted_going_in":
                     muscle_status(doses[m], params, m, latest, strictly_before=True)["state"]}
                    for m in used]
            out.append({"id": uid, "type": "limited", "about_date": str(latest),
                        "text": "In the session on %s, did a muscle that wasn't recovered hold back a "
                                "lift? Which muscle, and how much (1 slightly, 2 clearly, 3 cut the "
                                "work short)?" % latest,
                        "model_predicted": pred,
                        "changes": "the evidence for k and mult.<muscle> (window length)",
                        "record": "feedback-add --state %s --measure limited --about-date %s "
                                  "--scope MUSCLE --value 1|2|3   (nothing limiting: --scope all "
                                  "--value 0)" % (state_path, latest)})
        effort = defaultdict(lambda: {"sets": [], "dose": 0.0, "muscles": set()})
        for r in rows:
            if r["date"] == latest and r["kind"] in RIR_KINDS:
                x = effort[r["key"]]
                x["sets"].append("%gx%s" % (r["weight"], r["reps"]))
                x["dose"] += sum(r["muscles"].values())
                x["muscles"].update(r["muscles"])
        short = shortfalls(rows)
        for key, x in sorted(effort.items(), key=lambda kv: -kv[1]["dose"]):
            uid = "rir:%s:%s" % (latest, norm(key))
            if uid in closed or (str(latest), norm(key)) in short:
                continue
            out.append({"id": uid, "type": "effort", "about_date": str(latest),
                        "exercise": names[key],
                        "text": "On %s (%s), how many reps did you have left at the end of the "
                                "hardest set?" % (names[key], " ".join(x["sets"])),
                        "changes": "that session's dose for " + ", ".join(
                            LABEL[m] for m in MUSCLE_IDS if m in x["muscles"]),
                        "record": 'feedback-add --state %s --measure rir --about-date %s --scope "%s" '
                                  "--value N" % (state_path, latest, names[key])})
    return out


def text_unknowns(items):
    if not items:
        return "Unknowns: none."
    out = ["Unknowns (%d). Ask what is worth asking; none are required." % len(items)]
    for u in items:
        out.append("- [%s] %s" % (u["id"], u["text"] if u["type"] != "note"
                                  else "Note on %s: \"%s\"" % (u["exercise"], u["text"])))
        if u.get("model_predicted"):
            out.append("    model going in: " + ", ".join(
                "%s %s" % (LABEL[p["muscle"]], p["predicted_going_in"]) for p in u["model_predicted"]))
        if u.get("changes"):
            out.append("    changes: " + u["changes"])
        if u.get("what_to_do"):
            out.append("    " + u["what_to_do"])
        out.append("    record: " + u["record"])
    return "\n".join(out)
