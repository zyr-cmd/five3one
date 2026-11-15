"""Every numeric assumption of the recovery lens, as a named parameter.

Each parameter has a default, a permitted range, and a basis:
  SOURCED            the number comes from published data
  DIRECTION-SOURCED  the direction comes from published data; the size is a judgement
  JUDGEMENT          no evidence found; a stated assumption
The state file can override any of them (param-set), within its range. References are
listed in docs/SOURCES.md; [n] in a note is its reference number there.
"""

from .muscles import MUSCLE_IDS

# name: (default, min, max, basis, note)
_P = {
    # Stimulus weight of one done set, by kind. Scale: a hard set at or near failure = 1.0.
    "stim.main": (0.2, 0.1, 0.5, "DIRECTION-SOURCED",
                  "work sets stopped at about half the possible reps recovered within 6 h, "
                  "even when doubled [1][3]"),
    "stim.main_top": (1.0, 0.6, 1.25, "SOURCED",
                      "the last main set is an AMRAP; 0 and 1 reps in reserve cost the same at 24 h [6]"),
    "stim.joker": (0.6, 0.3, 1.0, "DIRECTION-SOURCED",
                   "heavy low-rep sets: 8x3 at 90% left no lasting strength deficit [5]"),
    "stim.bbb": (0.3, 0.15, 0.75, "DIRECTION-SOURCED",
                 "5x10 far from failure, but light high-rep work still depressed jumping at 24 h [17]"),
    "stim.accessory": (0.6, 0.3, 1.0, "JUDGEMENT",
                       "effort unknown unless stated; single-joint work can cost more [11]"),
    # Stimulus weight when the lifter states reps in reserve (RIR) for an exercise on a date.
    "rir.0_1": (1.0, 0.8, 1.25, "SOURCED", "failure and 1 RIR both -3% bar velocity at 24 h [6]"),
    "rir.2_3": (0.4, 0.25, 0.7, "DIRECTION-SOURCED",
                "3 RIR: acute loss about a third of failure, none at 24 h [6]"),
    "rir.4_plus": (0.2, 0.1, 0.4, "DIRECTION-SOURCED", "half-rep sets recovered within 6 h [1][3]"),
    # Dose bands: a session dose up to `upto` hard-set equivalents gives a window of [lo, hi] days.
    "band1.upto": (1.5, 0.5, 3.0, "JUDGEMENT", "band edge"),
    "band1.lo": (0.0, 0.0, 1.0, "SOURCED", "non-failure 3x5 and 6x5 back within 6 h [1][3]"),
    "band1.hi": (1.0, 0.0, 2.0, "SOURCED", "non-failure 3x5 and 6x5 back within 6 h [1][3]"),
    "band2.upto": (3.5, 1.5, 5.0, "JUDGEMENT", "band edge"),
    "band2.lo": (1.0, 0.0, 2.0, "DIRECTION-SOURCED", "3 sets to failure: 24 to 72 h [1][3][16]"),
    "band2.hi": (2.0, 1.0, 3.0, "DIRECTION-SOURCED", "3 sets to failure: 24 to 72 h [1][3][16]"),
    "band3.upto": (6.0, 3.5, 8.0, "JUDGEMENT", "band edge"),
    "band3.lo": (1.0, 0.0, 2.0, "DIRECTION-SOURCED",
                 "4 sets to failure: under 24 h (bench) to 72 h (squat) [7]"),
    "band3.hi": (3.0, 2.0, 4.0, "DIRECTION-SOURCED",
                 "4 sets to failure: under 24 h (bench) to 72 h (squat) [7]"),
    "band4.upto": (9.0, 6.0, 14.0, "JUDGEMENT", "band edge"),
    "band4.lo": (2.0, 1.0, 3.0, "SOURCED", "6 sets to failure back at 48 h [6]"),
    "band4.hi": (4.0, 3.0, 5.0, "SOURCED",
                 "8 sets not back at 72 h [5]; peak torque back at 96 h [8]"),
    "band5.lo": (3.0, 2.0, 4.0, "JUDGEMENT", "any dose above band 4; extrapolated"),
    "band5.hi": (5.0, 4.0, 7.0, "JUDGEMENT",
                 "extrapolated; total work still down at 96 h after 8 sets to failure [8]"),
    # Personal multiplier on every window.
    "k": (1.0, 0.5, 2.0, "JUDGEMENT",
          "global personal multiplier; the literature points above 1 for a lifter returning "
          "from a layoff [4][18]; adjust from feedback"),
}
for _m in MUSCLE_IDS:
    _P["mult." + _m] = (1.0, 0.5, 2.0, "JUDGEMENT",
                        "no evidence for a muscle-specific split from 1.0 [7][11][12]")

PARAMS = {name: {"default": d, "min": lo, "max": hi, "basis": basis, "note": note}
          for name, (d, lo, hi, basis, note) in _P.items()}


def check_param(name, value):
    """Return the validated float, or raise ValueError with the allowed range."""
    if name not in PARAMS:
        raise ValueError("unknown parameter %r (see param-list)" % name)
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s: not a number: %r" % (name, value))
    p = PARAMS[name]
    if not p["min"] <= v <= p["max"]:
        raise ValueError("%s: %g is outside the permitted range %g to %g"
                         % (name, v, p["min"], p["max"]))
    return v


def resolve_params(state=None):
    """{name: value} with the state file's overrides applied."""
    values = {name: p["default"] for name, p in PARAMS.items()}
    for name, v in ((state or {}).get("params") or {}).items():
        values[name] = check_param(name, v)
    return values
