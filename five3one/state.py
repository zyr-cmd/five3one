"""The state file: what the export cannot regenerate.

One JSON file kept in the owner's project and passed with --state. It holds exercise
map overrides, parameter overrides with a log, feedback, and which unknowns have been
answered or dismissed. Commands change it; nothing else should. Every write bumps
`revision`, which `update` stamps into the muscle file so a lost or stale state file is
detected on the next run (see cmd_update --state-revision).
"""

import json
import os

from .muscles import MUSCLE_IDS
from .params import check_param
from .text import norm

SCHEMA = 1
MEASURES = {
    # measure: (scope kind, min, max, meaning)
    "limited": ("muscle", 0, 3, "how much the muscle held back a lift that session "
                                "(0 not at all, 1 slightly, 2 clearly, 3 cut the work short)"),
    "sore": ("muscle", 0, 3, "soreness before that session; context only, moves nothing"),
    "rir": ("exercise", 0, 10, "reps in reserve on that exercise that session"),
}


class StateError(Exception):
    pass


def empty_state():
    return {"schema": SCHEMA, "revision": 0, "exercise_map": {}, "params": {},
            "param_log": [], "feedback": [], "answered": [], "dismissed": []}


def load_state(path):
    """Return the validated state dict. A missing path returns None (caller decides)."""
    if not path:
        return None
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError) as exc:
        raise StateError("cannot read state file %s: %s" % (path, exc))
    if not isinstance(st, dict) or st.get("schema") != SCHEMA:
        raise StateError("state file %s has schema %r; this version reads schema %d only"
                         % (path, st.get("schema") if isinstance(st, dict) else None, SCHEMA))
    base = empty_state()
    for k, v in base.items():
        st.setdefault(k, v)
    for name, weights in st["exercise_map"].items():
        _check_weights(name, weights)
    for name, v in st["params"].items():
        try:
            check_param(name, v)
        except ValueError as exc:
            raise StateError("state file %s: %s" % (path, exc))
    return st


def save_state(path, state):
    """Atomic write; bumps the revision. Returns the new revision."""
    state["revision"] = int(state.get("revision", 0)) + 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return state["revision"]


def _check_weights(name, weights):
    if not isinstance(weights, dict) or not weights:
        raise StateError("mapping for %r must name at least one muscle" % name)
    for m, w in weights.items():
        if m not in MUSCLE_IDS:
            raise StateError("mapping for %r: unknown muscle %r. Muscles: %s"
                             % (name, m, ", ".join(MUSCLE_IDS)))
        if w not in (0.5, 1.0):
            raise StateError("mapping for %r: weight for %s must be 1 or 0.5, got %r" % (name, m, w))


def set_mapping(state, exercise, weights):
    _check_weights(exercise, weights)
    key = exercise.strip()
    for existing in list(state["exercise_map"]):
        if norm(existing) == norm(key) and existing != key:
            del state["exercise_map"][existing]
    changed = state["exercise_map"].get(key) != weights
    state["exercise_map"][key] = dict(weights)
    return changed


def set_param(state, name, value, reason, date_str):
    v = check_param(name, value)
    from .params import PARAMS
    old = state["params"].get(name, PARAMS[name]["default"])
    if old == v:
        return False, old, v
    state["params"][name] = v
    state["param_log"].append({"date": date_str, "param": name, "old": old, "new": v,
                               "reason": reason})
    return True, old, v


def feedback_id(measure, about_date, scope):
    return "%s:%s:%s" % (measure, about_date, norm(scope) if measure == "rir" else scope)


def unknown_id_for(measure, about_date, scope):
    """The unknown that a piece of feedback answers."""
    if measure == "limited":
        return "limited:%s" % about_date
    if measure == "rir":
        return "rir:%s:%s" % (about_date, norm(scope))
    return None


def add_feedback(state, measure, about_date, scope, value, recorded, source="chat", quote=None):
    """Idempotent by id: the same answer twice changes nothing; a different value replaces."""
    if measure not in MEASURES:
        raise StateError("unknown measure %r. Measures: %s" % (measure, ", ".join(sorted(MEASURES))))
    kind, lo, hi, _ = MEASURES[measure]
    if kind == "muscle" and scope != "all" and scope not in MUSCLE_IDS:
        raise StateError("scope for %s must be a muscle id or 'all'. Muscles: %s"
                         % (measure, ", ".join(MUSCLE_IDS)))
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise StateError("value must be a whole number, got %r" % (value,))
    if scope == "all" and (measure != "limited" or v != 0):
        raise StateError("scope 'all' is only for recording that nothing was limiting "
                         "(--measure limited --value 0)")
    if not lo <= v <= hi:
        raise StateError("%s value must be %d to %d, got %d" % (measure, lo, hi, v))
    fid = feedback_id(measure, about_date, scope)
    entry = {"id": fid, "measure": measure, "about_date": about_date, "scope": scope,
             "value": v, "recorded": recorded, "source": source, "quote": quote}
    changed = True
    for i, old in enumerate(state["feedback"]):
        if old["id"] == fid:
            if (old["value"], old.get("quote")) == (v, quote):
                changed = False
            else:
                state["feedback"][i] = entry
            break
    else:
        state["feedback"].append(entry)
    uid = unknown_id_for(measure, about_date, scope)
    if uid and uid not in state["answered"]:
        state["answered"].append(uid)
        changed = True
    return changed, entry


def dismiss(state, unknown_id):
    if unknown_id in state["dismissed"]:
        return False
    state["dismissed"].append(unknown_id)
    return True


def summary(state):
    if state is None:
        return "state: none"
    n_lim = sum(1 for f in state["feedback"] if f["measure"] == "limited")
    return ("state: revision %d, %d mapping override(s), %d parameter override(s), "
            "%d feedback entr%s (%d on limited performance)"
            % (state["revision"], len(state["exercise_map"]), len(state["params"]),
               len(state["feedback"]), "y" if len(state["feedback"]) == 1 else "ies", n_lim))
