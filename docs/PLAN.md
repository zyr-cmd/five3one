# Muscle map: design plan (v2)

Status: revised after an independent review; awaiting the owner's approval. No feature code exists yet. Section 14 lists what the review changed.

## 1. What this is for

The tool answers three questions from a Five3One export:

- **A. Program:** per muscle, how much work is listed in the logged sessions, how much was done, and where are the gaps?
- **B. Session:** what did one session hit?
- **C. Recovery:** what has been hit recently, and is each muscle likely recovered yet?

The decision it feeds: from what date are the muscles needed by the next main lift likely recovered, and so should the next session be moved or trimmed.

### Users, in priority order

1. **An agent (Claude) working in the owner's project.** It starts each session with the project's docs but without the export and without earlier conversations. It runs commands, reads compact output, asks the human at most one question, and records the answer. It never does arithmetic and never invents a mapping.
2. **The human.** He logs sets in the Five3One app, drops an export into a chat, and reads a short answer and a body diagram. He does not learn syntax, edit files, or judge model parameters.

### Non-goals for this version

- Nutrition, energy deficit, sleep and cardio are not modelled. They shift recovery, so the windows are expected to drift; the single user multiplier (section 5C) is how that is absorbed.
- Time of day: the export has dates only, so recovery resolves to whole days.
- Whole-body (systemic) fatigue, effort estimated from e1RM, and automatic parameter fitting are deferred (section 13).

## 2. The experience

No new human touchpoints.

1. **After training: drop the export into a project chat.** The agent runs one command (`update`). It gets the refreshed report with a muscles section, an HTML body diagram to send, and at most one question.
2. **Weekly review (existing scheduled task, no human present).** It reads the stored report and uses lens A. It asks no muscle questions.
3. **In the gym (optional).** Free text in the app's Notes field. The tool lists notes from sessions newer than the last stored report; the agent records any soreness or effort the note states, quoting the note as the source.

## 3. Rules taken from the owner

- A set is **done** when it is ticked **and** its reps are above zero. This holds for every set type, accessories included.
- An unticked set is not done. It is never called failed.
- A set with a blank tick is not done.

One function `is_done(event)` in `parse.py` implements this and every command uses it. This changes existing output in one case (a ticked set with 0 reps), which is intended.

## 4. Data model

### 4.1 Muscle groups

Sixteen groups with snake_case ids, each a region on the diagram:

`chest, front_delts, side_delts, rear_delts, triceps, biceps, forearms, lats, upper_back, lower_back, abs, glutes, quads, hamstrings, adductors, calves`

A constant in code, because the diagram depends on it.

### 4.2 Exercise map

`exercise -> {muscle: weight}`, weight 1.0 for a primary mover and 0.5 for a secondary one (fractional-set counting: one set of bench is 1 chest set and 0.5 triceps set). The 0.5 is a counting convention with a cited source, not a fatigue measurement.

- Lookup goes through the existing `text.norm` (case, whitespace and hyphens ignored), so "Dead Lift", "deadlift" and "Chest Supported Row" resolve.
- The default map is built once, at build time, against the owner's real exercise names, and ships in code.
- State-file overrides add or replace entries.
- An exercise with no mapping is never guessed. Its sets go to an `unmapped` bucket that every output reports. The tool proposes nothing; the agent proposes a mapping and the human confirms with a yes or no.

### 4.3 Set classes

| Class | Source | Counted |
|---|---|---|
| warmup | `Warm up` rows of a main lift | no |
| main | `Main` rows | yes |
| joker | `Joker sets` rows | yes |
| bbb | `Boring but BIG sets` rows | yes |
| accessory | rows with an empty `Set`, and `Warm up` rows of non-main exercises | yes |
| other | any other `Set` value | reported, not counted |

There is no separate "top set" class in this version.

### 4.4 Hard sets

Lenses A and B count sets. Lens C needs to know how demanding a session was for a muscle, and uses **hard-set equivalents**: each done set counts `class weight x muscle weight`.

Class weights are parameters (section 8). If the human has stated reps in reserve for an exercise on a date, that overrides the class weight for those sets. Every figure records which source it used. Effort is not estimated from e1RM in this version (section 14, item 1).

## 5. The three lenses

### A. Program

Window: the last `--weeks N` calendar weeks ending at `--as-of` (default 4), within the current training block.

Per muscle:

- **listed sets per week:** every counted row in the logged sessions, done or not, excluding jokers (optional by the owner's rule). This is what the app listed on days he trained. It is not a prescription, and skipped days contribute nothing.
- **done sets per week:** done sets only.
- Both as fractional totals with the direct (weight 1.0) part shown separately.
- **frequency:** days per week with at least one done set.
- **flags**, at most three per report, ranked: a muscle with no done direct set in the window; a muscle whose done sets are under half of listed.
- A separate one-line list: exercises listed in the window and never done.

Volume reference bands from the literature are not used for flags in this version.

### B. Session

For one date (default: the latest session): per muscle, done sets and hard-set equivalents, with the contributing exercises.

### C. Recovery

A time-window model, in days, with no invented units.

For each muscle, take the most recent date on which it received done work, and that date's dose `d` (hard-set equivalents for the muscle that day). The muscle's expected recovery window is

`[lo(d), hi(d)] x k`

- `lo` and `hi` are days, non-decreasing in `d`, defined by a small table of dose bands (section 8). They come from the literature pass and carry citations.
- `k` is one user multiplier, default 1.0. It is the only personal parameter.
- If two sessions hit the muscle within an open window, the later window end wins and the doses are not summed. This is a stated simplification.

State at `--as-of` (required for this lens; an as-of before the last session is an error):

- before `last + lo`: **likely not recovered**
- between: **uncertain**
- after `last + hi`: **likely recovered**

Outputs per muscle: last hit date, dose, the window as two dates, the state, and the contributing sets.

**Next-session line.** The next main lift is the one longest since trained among those remaining this week (existing `status` logic); if the week is complete, the lift that opened the previous week. Its companion BBB lift is taken from the most recent session with the same main lift. The line gives the earliest date on which every primary muscle of those two lifts is past its `lo`, and the date on which all are past `hi`. It is valid only if no session has been logged since, and says so.

### Honesty about C

C is a heuristic. The windows are literature ranges, not measurements of this person, and the only personal adjustment is `k`. Every C output states the value of `k` and how many feedback points support it.

## 6. State file

One JSON file stored in the owner's project (never in this repo), passed with `--state PATH`. It holds only what the export cannot regenerate.

```json
{
  "schema": 1,
  "revision": 7,
  "exercise_map": {"pec fly": {"chest": 1.0, "front_delts": 0.5}},
  "k": 1.0,
  "feedback": [
    {"id": "fb-2026-01-10-hamstrings-pre", "recorded": "2026-01-10", "about_date": "2026-01-10",
     "scope_type": "muscle", "scope": "hamstrings", "measure": "pre_session_soreness",
     "value": 2, "source": "chat", "quote": null}
  ],
  "answered": ["q-pre-2026-01-10"],
  "skipped": []
}
```

Rules:

- The agent changes it only through commands. Each command validates, writes atomically, increments `revision`, and prints what changed and the new revision.
- Writes are idempotent by `id`: recording the same feedback twice changes nothing.
- An unknown `schema` is an error.
- **State loss is detected.** `update` stamps the state revision and counts into the report. On the next run the agent passes `--state-revision N` from the stored report (the same pattern as `--min-sessions`); a missing state file or a lower revision is a refusal, not a silent fresh start. With no state and no expected revision, output says `state: none`.
- One save-back point: after `update` and any feedback command, the agent saves the state file to the project once, at the end of the session.

Measures:

- `pre_session_soreness`: 0 to 3 for a muscle, as it was before a given session.
- `rir`: reps in reserve for an exercise on a date, with a set class.

## 7. Commands

Flat, hyphenated names in the existing style. All accept `--json`. Commands that need no export take no CSV.

| Command | CSV | Purpose |
|---|---|---|
| `update --out-dir DIR [--state PATH --state-revision N] [--as-of D] [--min-sessions N]` | yes | Existing entry point, extended: muscles section in `progress.md`, `DIR/muscles.html`, at most one question. |
| `muscles --lens program\|session\|recovery [--date D] [--weeks N] [--as-of D] [--state PATH] [--html PATH]` | yes | One lens on demand. |
| `explain --muscle M --lens ... [--as-of D]` | yes | The sets, parameters and feedback behind one figure. |
| `question [--state PATH] [--as-of D]` | yes | The pending question, if any. |
| `feedback-add --state PATH --question ID ...` | no | Record an answer and mark the question answered. |
| `question-skip --state PATH --question ID` | no | Mark a question skipped; it is not asked again. |
| `map-set --state PATH EXERCISE muscle=weight ...`, `map-list [--state PATH]` | no | Exercise map overrides. |
| `k-set --state PATH VALUE --reason TEXT` | no | Set the user multiplier. |

`report` gains `--state` so that `update` and `report` still produce identical markdown.

## 8. Parameters and their sources

All numeric assumptions live in one module as named parameters, each with a default, a plausible range and a citation:

- the secondary-mover weight (0.5);
- class weights for hard-set equivalents (main, joker, bbb, accessory);
- the dose bands and their `lo` and `hi` days.

Defaults are set from a literature pass that is a build task, and are not written from memory. Where the literature does not support a distinction (for example between muscle groups), one shared value is used and the parameter is labelled "no evidence for a split".

## 9. Question protocol

At most **one** question per `update`, and none when no human is present.

Priority:

1. **Unmapped exercise.** The agent proposes a mapping; the human answers yes or no.
2. **Pre-session soreness.** Asked about the session just logged, because that is when a prediction can be tested: "Before today's session, was anything still sore or limiting? Which, and how much (1 mild, 2 noticeable, 3 limiting)?" The answer is recorded against that date for each muscle named; "nothing" is recorded as zeros for the muscles the session's main and BBB lifts use.
3. **Effort.** Reps in reserve on one BBB or accessory lift from the session just logged.

Rules:

- A question is emitted only if its answer can change something shown in that report.
- Every question has an id. `feedback-add --question ID` marks it answered; `question-skip` retires it. An unanswered question is asked at most twice, then retired.
- The printed `record` line is a complete, runnable command.

## 10. Use of feedback

This version stores feedback and reports it against predictions; it does not fit anything.

`muscles --lens recovery` shows a small tally once feedback exists: of the pre-session ratings recorded, how many fell in a window the model called likely recovered, uncertain or likely not recovered, and how many of each were rated sore. The agent uses that tally to propose a change to `k` to the human in plain terms ("you have been sore at the predicted-recovered point in 4 of 5 sessions; lengthen the windows by a quarter?"). One parameter, changed one step at a time.

## 11. Outputs

### progress.md muscles section

Regenerated whole on each export, and kept short because the report is loaded in every chat:

- the next-session line;
- recovery table: muscle, last hit, state, window dates;
- program table: muscle, listed and done sets per week, frequency; then up to three flags;
- exercises listed and never done; unmapped exercises;
- `state: revision N, k = ..., feedback points: ...` or `state: none`.

### JSON

The same content with full provenance. Field names are documented in the package docstring and covered by a golden-file test.

### HTML

One self-contained file: front and back body outlines with the sixteen regions; one panel per lens; a colour scale readable in light and dark that does not rely on hue alone; the same numbers in a table underneath. Rendered from the JSON, so the picture cannot disagree with the data.

## 12. Project integration (outside this repo)

- `CLAUDE.md` routing table: one row for muscles, recovery and the next-session line.
- `log-update.md`: the extended `update` call with `--state` and `--state-revision`, the single save-back, sending `muscles.html`, asking the one question. The single-file fallback is marked as producing a report without the muscles section.
- Weekly review task prompt: use the program table; ask no muscle questions.
- One new project file for the state.

## 13. Acceptance

1. Existing command outputs are unchanged except: the added muscles section in `report` and `update`, and the done rule applied to ticked 0-rep sets.
2. Unit tests on synthetic fixtures: the done rule; set classes including `other`; map lookup through `norm`; fractional counting; unmapped handling; calendar-week windows; flag cap; recovery windows and states at the boundaries; overlapping windows; the next-session line including the week-complete case; as-of before last session is an error; state validation, revision check, idempotent writes, state-loss refusal; question priority, the one-question cap, skip and retire.
3. Property tests: adding a done set never lowers a muscle's count or shortens its window; lens A and B output does not depend on `--as-of` beyond the window; a later `--as-of` never moves a state backwards.
4. Golden-file tests for the muscles section and the JSON.
5. HTML: an automated check that every region id is present and coloured from the data, plus a rendered image checked by eye for each lens.
6. **Cold-user test**, scripted and repeated: a fresh agent given only the project docs and a synthetic export must run `update`, report the next-session line, ask the one question, record an answer, save the state, and explain a flagged muscle with `explain`, without reading the source. It is also run with the state file missing, where it must stop and report the refusal.
7. On the owner's real export: no unmapped exercises; the report's flags are at most three; and one recent week chosen by the owner is shown to him as a sanity check.

Deferred, with the reason:

- **Effort from e1RM.** Inverting Epley gives absurd reps in reserve for sub-maximal sets and the wrong sign on a fatigued day.
- **Decay model with fatigue thresholds.** The threshold is in invented units and cannot be sourced or identified from a fixed weekly program.
- **Automatic calibration.** Around three sessions per lift per block cannot support per-muscle fitting.
- **Systemic fatigue term.** Wait for evidence that per-muscle windows alone mispredict.
- **Volume reference bands.**

## 14. What the review changed

1. Effort estimated from e1RM was removed; class weights and stated reps in reserve remain.
2. The exponential decay model with a fatigue threshold was replaced by recovery windows in days with one user multiplier.
3. Soreness is asked about the state before the session just logged, not "today".
4. `calibrate`, per-muscle parameters and the parameter log were removed; feedback is stored and tallied.
5. "Programmed" became "listed in logged sessions", windows became calendar weeks, jokers were excluded from listed, and flags were capped.
6. The next-session line became an earliest-date statement with a rule for a completed week.
7. State-only commands no longer need a CSV, and state loss is detected through a revision stamped into the report.
8. Questions were cut to one per export with skip and retire rules, and none when no human is present.
9. One `is_done` function, map lookup through `norm`, an `other` set class, and snake_case muscle ids.

Kept against the review's advice: the HTML body diagram stays in this version, because the owner asked for it; it is built after the numbers.

## 15. Build order

1. `is_done` applied everywhere; set classes.
2. Exercise map against the real exercise names; lenses A and B; text and JSON.
3. State file, revision guard, map and feedback commands, question protocol.
4. Literature pass for the parameters in section 8.
5. Lens C, the next-session line, `explain`.
6. HTML renderer.
7. `update` and `report` integration; project doc changes.
8. Cold-user test.

## 16. Open questions for the owner

1. Are unticked accessory rows a prescription he intends to do, or a menu to pick from? The answer decides whether "done under half of listed" is a useful flag or noise.
2. Is sixteen the right granularity, in particular keeping forearms and adductors and splitting upper back from lats?
