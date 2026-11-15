# Muscle map: design plan (v3)

Status: awaiting the owner's agreement. No feature code exists.

This version is built from the owner's brief. Section 1 is the brief. Every design element in sections 2 to 8 names the brief line it serves. Anything that serves no line is in section 9 as a proposed addition for the owner to accept or reject.

## 1. The brief

In the owner's words.

| Id | Brief |
|---|---|
| B1 | A "tiny .py or similar that eats the workout.csv" and makes the body diagram that "colours in muscle groups to indicate what's been trained". |
| B2 | Lens A, program evaluation: "what is actually getting hit across the program (any missing links)". |
| B3 | Lens B, individual session: "what just got hit". |
| B4 | Lens C, rolling recovery: "what has been hit recently and how likely is it to be recovered by now", tuned "based on literature on recovery of muscle groups, type of training stimulus, and user response (qualitative feedback)". |
| B5 | "Useful for an agentic worker." "The visual aid is just to keep the meat proxy (me) happy." |
| B6 | "The Claude worker can ask questions about the workout to estimate likely fatigue costs." |
| B7 | "Agentic user first - the agent can use it, can control it, and can get the qualitative bits from the human as needed." |
| B8 | Work with the project as it is (its docs, the export flow, the scheduled tasks) "with minimal extra work for the human, to deliver maximal value". |

Rules the owner stated:

| Id | Rule |
|---|---|
| R1 | A ticked set is done. An unticked set is not done (never "failed"). |
| R2 | A line with 0 reps is not done. |
| R3 | Accessory rows are a menu, not a prescription. |
| R4 | Soreness is not necessarily an indicator of recovery. |
| R5 | An agent session starts inside the project, with its docs. It does not have the export until the owner supplies one. |

Agreed experience (E), proposed on 2026-11-16 and accepted by the owner as reasonable:

- No new human touchpoints: he logs in the app, drops an export into a project chat, and a weekly scheduled review runs.
- The existing `update` command also produces the muscle output.
- The muscle output is a section of the stored `progress.md`.
- Recovery is stored as dates, so a later session can read it without the export.
- One new stored file holds what the export cannot regenerate.
- The headline is a line about the next session.

## 2. What is counted (R1, R2, R3)

- A set counts when it is ticked and its reps are above zero. One function implements this and every command uses it.
- Sets that are listed and not done are ignored everywhere. Nothing reports missed or unticked work.
- Warm-up sets of a main lift are not counted.

## 3. Muscles and the exercise map (B1, B2, B3)

- Sixteen muscle groups, each a region on the diagram: chest, front delts, side delts, rear delts, triceps, biceps, forearms, lats, upper back, lower back, abs, glutes, quads, hamstrings, adductors, calves.
- Each exercise maps to muscles with a weight: 1.0 for a primary mover, 0.5 for a secondary one. One set of bench is 1 chest set and 0.5 triceps set.
- The default map is built against the owner's real exercise names and ships in code. Lookup ignores case, spacing and hyphens.
- An exercise with no mapping is never guessed. Its sets are reported as unmapped, and it appears in the agent's list of unknowns (section 6).

## 4. The lenses

### A. Program (B2)

Over the last N calendar weeks of the current training block (default 4):

- done sets per week per muscle, with the direct (weight 1.0) part shown separately;
- days per week each muscle is hit;
- **missing links:** muscles that received no direct done work in the window, and muscles hit only as secondary movers.

### B. Session (B3)

For one session (default: the latest): done sets per muscle and the exercises that produced them.

### C. Recovery (B4)

**What has been hit recently:** per muscle, the date it was last hit and how hard.

**How hard** is a dose: the sum over done sets of `stimulus weight x muscle weight`. The stimulus weight is where "type of training stimulus" enters. It depends on the kind of set (main, joker, BBB, accessory) and on stated effort where the owner has given it. The literature pass decides which further distinctions have support (for example proximity to failure, volume in one session, or work at long muscle length); a parameter exists only for a distinction with a cited source.

**How likely it is recovered by now:** each muscle gets a recovery window in days, `[lo, hi]`, that lengthens with dose. At a given date the muscle is:

- **likely not recovered** before `last hit + lo`;
- **uncertain** between;
- **likely recovered** after `last hit + hi`.

The three states are the answer to "how likely". A finer probability would claim precision the evidence does not have.

**Tuning, on the three axes the brief names:**

| Axis | How it enters | Who changes it |
|---|---|---|
| Literature on muscle groups | A per-muscle multiplier on the window. Default from the literature where it supports a difference, otherwise 1.0 and labelled "no evidence for a split". | Agent, with a reason |
| Type of training stimulus | The stimulus weights above. | Agent, with a reason |
| User response | Feedback (section 6) is stored and tallied against the model's predictions. One global multiplier and the per-muscle multipliers are adjusted from it. | Agent proposes in plain words, owner agrees |

Nothing is fitted automatically. With about three sessions per lift per block there is not enough data to fit per-muscle values, so changes are explicit, one at a time, each logged with its reason.

Corrections carried over from the independent review, kept because they fix something that was wrong:

- Effort is not estimated from e1RM. Inverting Epley gives absurd reps in reserve on sub-maximal sets and the wrong sign on a fatigued day.
- The earlier decay curve with a fatigue threshold is gone. Its threshold was in invented units that no source could supply.
- The export has dates only, so recovery resolves to whole days, and lens C requires the owner's local date.

## 5. Parameters (B4, B7)

Every numeric assumption is a named parameter with a default, a plausible range and a citation: the secondary-mover weight, the stimulus weights, the dose-to-window table, and the muscle multipliers.

Defaults come from a literature pass that is a build task, not from memory.

## 6. The agent's side (B5, B6, B7)

**Use.** Every command gives compact text and full JSON. `explain` returns the sets, parameters and feedback behind any one figure. The agent never does arithmetic.

**Control.** The agent can read and set every parameter and every exercise mapping:

- `param-list` shows each parameter's default, current value and source;
- `param-set NAME VALUE --reason TEXT` changes one and logs it;
- `map-set EXERCISE muscle=weight ...` changes a mapping.

**Getting the qualitative bits.** The tool reports what it does not know about recent sessions as a ranked list of unknowns, each with what the answer would change:

- an unmapped exercise;
- for the session just logged, whether a muscle that was not recovered held back a lift, and how much (R4: this is the recovery signal, not soreness; and it is asked about the session just logged because that is when a prediction can be checked);
- how hard a BBB or accessory lift was, in reps in reserve;
- free-text notes in the export from sessions newer than the stored report, for the agent to read.

The agent decides which of these to ask and how many, in the conversation it is in. It records answers with `feedback-add`. An answered or dismissed unknown is not listed again. When no human is present (the weekly task) the agent asks nothing.

Soreness, if the owner mentions it, is stored as context and does not move the model.

## 7. State (E, R5)

One JSON file in the owner's project, passed with `--state`. It holds only what the export cannot regenerate: mapping overrides, parameter overrides with their log, feedback, and which unknowns are answered or dismissed.

- The agent changes it only through commands, then saves it back to the project once at the end of the session.
- Commands that need no export take no CSV.
- With no state file the tool runs on defaults and says `state: none`.

## 8. Outputs and project integration (B1, B5, B8, E)

- **`update`** (existing entry point) also writes the muscles section into `progress.md`, writes the body diagram as one HTML file, and prints the unknowns.
- **progress.md muscles section:** the next-session line; the recovery table (muscle, last hit, state, window dates); the program table and missing links; unmapped exercises; the state summary.
- **Next-session line:** the earliest date on which the muscles used by the next main lift and its BBB lift are past `lo`, and the date they are all past `hi`. Valid only while no later session is logged, and it says so.
- **Body diagram:** front and back outlines with the sixteen regions, one panel per lens, the same numbers in a table underneath. Rendered from the JSON so the picture cannot disagree with the data.
- **Project docs:** one new row in the routing table; the update procedure gains `--state`, the save-back and sending the diagram.
- **Weekly review task:** reads the program table. Wording to be shown to the owner before the task is changed.

## 9. Proposed additions (not in the brief; owner to accept or reject each)

| # | Addition | Why | Cost |
|---|---|---|---|
| P1 | **State-loss guard.** `update` stamps a state revision into `progress.md`; the next run refuses if the state file is missing or older. | The tuning lives in one project file. Losing it would otherwise look like a fresh start. | One extra argument on `update`. |
| P2 | **Idempotent feedback.** Recording the same answer twice changes nothing. | Two sessions might record the same answer. | None for the owner. |
| P3 | **Prediction tally in lens C.** How often a muscle the model called recovered was reported as limiting. | It is the evidence for changing a multiplier. | A few lines in the output. |

## 10. Cut or deferred

- Adherence reporting of any kind (cut: not in the brief, R3).
- Effort from e1RM, the threshold decay model, automatic calibration (cut: unsound, section 4C).
- Whole-body fatigue term (deferred until per-muscle windows are shown to mispredict).
- Weekly volume reference bands (deferred: not in the brief).

## 11. Size

B1 asked for something small. The feature is three lenses, one state file and these commands: `update` (existing), `muscles`, `explain`, `unknowns`, `feedback-add`, `param-list`, `param-set`, `map-set`.

## 12. Build order

1. The done rule in one function; set kinds.
2. Exercise map against the real names; lenses A and B; text and JSON.
3. State file; `map-set`, `param-set`, `feedback-add`; unknowns.
4. Literature pass for the parameters (can run in parallel with 1 to 3).
5. Lens C, the next-session line, `explain`.
6. Body diagram.
7. `update` integration and project doc changes.
8. Independent code review, then a cold-user test: a fresh agent with only the project docs and a synthetic export runs the whole flow.

## 13. Open question for the owner

Is sixteen the right set of muscle groups, in particular keeping forearms and adductors and splitting upper back from lats?
