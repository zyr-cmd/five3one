"""
five3one - Read a Five3One (5/3/1 BBB) CSV export without re-deriving its quirks.

Stdlib only, deterministic, no network. Point it at an export and get correct
figures in one call instead of reading the raw CSV.

USAGE
  python3 -m five3one CSV COMMAND [options]       (--json works anywhere)
  Install: pip install git+https://github.com/zyr-cmd/five3one@COMMIT

AGENT ENTRY POINTS
  update  --out-dir DIR [--as-of YYYY-MM-DD] [--min-sessions N]
        One call for a new export: CSV is the NEW export. Validates it, refuses if
        it has fewer than N sessions (pass the "sessions logged" figure from the
        current progress.md), then writes DIR/workouts.csv and DIR/progress.md.
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

MUSCLE COMMANDS (design: docs/PLAN.md; evidence: docs/SOURCES.md)
  Only done sets count: ticked AND reps above zero. Listed-but-not-done sets are ignored.
  muscles   --lens program [--weeks N] [--as-of D]   Done sets per week per muscle.
            --lens session [--date D]                What one session trained.
            --lens recovery --as-of D                Last hit, recovery window, state, and the
                                                     next-session line. --as-of is required.
            [--state PATH] [--html PATH]             --html writes the body diagram.
  explain   --muscle M [--as-of D] [--state PATH]    Sets, parameters and feedback behind
                                                     one muscle's figures.
  unknowns  [--as-of D] [--notes-since D] [--state PATH]
            What the tool does not know about recent sessions (did a muscle limit a lift,
            reps in reserve, notes to read), each with what it changes and the command
            that records it. Ask the owner what is worth asking; none are required.
  update    also takes --state PATH, --state-revision N (the state_revision in the stored
            muscles.csv; refuses if the state file is missing or older) and --notes-since D.
            It writes muscles.csv and muscles.html beside progress.md and prints unknowns.
  An exercise with done sets and no muscle mapping stops the muscle commands with the
  exact map-set command to run. Nothing is guessed.

STATE COMMANDS (no CSV argument; each bumps the state revision; save the file back)
  map-set --state PATH "EXERCISE" MUSCLE=1 [MUSCLE=0.5 ...]     map-list [--state PATH]
  param-set --state PATH NAME VALUE --reason TEXT [--as-of D]   param-list [--state PATH] [--all]
  feedback-add --state PATH --measure limited|rir|sore --about-date D --scope S --value V
               [--source chat|note] [--quote TEXT] [--as-of D]
       limited: scope = muscle id, value 0-3 (how much it held back a lift that session);
                "--scope all --value 0" records that nothing was limiting.
       rir:     scope = exercise name, value = reps in reserve on its hardest set.
       sore:    scope = muscle id, 0-3. Context only: soreness is not a recovery signal.
  feedback-remove --state PATH ID   (remove a wrong entry; reopens its unknown)
  unknown-dismiss --state PATH ID

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
7. SetCompleted is per set and is the record for every set type, accessories
   included: ticked = done, unticked = not done (not "failed"). A set logged
   with 0 reps is not done, whatever its tick.
8. BBB for a lift is done on ANOTHER lift's main day (frequency swap), so a
   lift's BBB history is not on the same dates as its main sets.

LAYOUT
  parse      CSV reading and the quirks above; one event dict per set
  model      blocks, e1RM, derived training maxes, lift lookup
  text       formatting helpers
  report     status, recap, report, update
  ingest     ingest (compare a new export with a stored copy)
  drilldown  session, lift, cycle, accessory, adherence, list-lifts, dump
  muscles    muscle groups, exercise map, lenses A (program) and B (session)
  params     every numeric assumption of the recovery lens, with its basis
  recovery   lens C, next-session line, prediction tally, unknowns
  state      the state file
  musclecmd  muscle and state commands
  render     the HTML body diagram
  cli        argument parsing and dispatch
"""

from .parse import (EXPECTED_COLUMNS, MAIN_SET_TYPES, STRONG_MAIN_TYPES, canonical_names,
                    events_for_dates, group_rows, load_events, main_lift_keys, parse_date,
                    session_dates)
from .model import (BLOCK_GAP_DAYS, WEEK_PCTS, derive_training_maxes, detect_blocks,
                    e1rm_history, epley, resolve_lift, top_e1rm)
from .report import REPORT_HEADER, build_report
from .cli import main
