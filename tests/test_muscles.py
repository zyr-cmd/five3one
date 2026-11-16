#!/usr/bin/env python3
"""Tests for the muscle lenses, the recovery model, the state file and its commands.
Synthetic exports only (no personal data). Run from the repo root: python3 -m pytest
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import five3one as f  # noqa: E402
from five3one import muscles as mu  # noqa: E402
from five3one import musclecmd as mc  # noqa: E402
from five3one import params as pm  # noqa: E402
from five3one import recovery as rc  # noqa: E402
from five3one import state as st  # noqa: E402
from five3one.render import render_html  # noqa: E402

HEADER = "Date,Name,Set,SetCompleted,Reps,Weights,CycleNr,WeekNr,Notes\n"
ROWS = [
    "2026-01-01,Squat,Warm up,true;true,5;5,40.0;50.0,1,1,",
    "2026-01-01,Squat,Main,true;true;true,5;5;8,65.0;75.0;85.0,1,1,",
    "2026-01-01,Squat,Joker sets,true;false,5;5,90.0;95.0,1,1,",
    "2026-01-01,Dead Lift,Boring but BIG sets,true;true;false;true;true,10;10;10;10;0,60.0;60.0;60.0;60.0;60.0,1,1,",
    "2026-01-01,Leg Extension,,true;true;true,12;12;12,30.0;30.0;30.0,1,1,quads were toast",
    "2026-01-01,Calf raises,,false;false,15;15,20.0;20.0,1,1,",
    "2026-01-03,Bench Press,Main,true;true;true,5;5;6,45.0;52.5;60.0,1,1,",
    "2026-01-03,Military Press,Boring but BIG sets,true;true,10;10,25.0;25.0,1,1,",
    "2026-01-03,Chest-Supported Row,,true;true;true,12;12;10,50.0;50.0;50.0,1,1,",
]


def write_csv(dirpath, rows, name="a.csv"):
    path = os.path.join(dirpath, name)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(HEADER + "".join(r + "\n" for r in rows))
    return path


def run_cli(*argv):
    p = subprocess.run([sys.executable, "-m", "five3one", *argv], cwd=ROOT,
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.csv = write_csv(self.dir, ROWS)
        self.ev = f.load_events(self.csv)[0]
        self.emap = mu.resolve_map()
        self.P = pm.resolve_params()
        self.state = os.path.join(self.dir, "state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def muscle(self, res, m):
        return next(x for x in res["muscles"] if x["muscle"] == m)


class CountingTests(Base):
    def test_done_rule_tick_and_reps(self):
        rows, _ = mu.counted_sets(self.ev, self.emap)
        bbb = [r for r in rows if r["kind"] == "bbb" and r["date"] == date(2026, 1, 1)]
        self.assertEqual(len(bbb), 3)  # one unticked, one ticked with 0 reps: neither counts
        self.assertFalse(any(r["name"] == "Calf raises" for r in rows))  # listed, not done
        self.assertFalse(any(r["kind"] == "warmup" for r in rows))

    def test_top_set_is_last_done_main_set(self):
        rows, _ = mu.counted_sets(self.ev, self.emap)
        tops = [(r["name"], r["reps"]) for r in rows if r["top"]]
        self.assertEqual(sorted(tops), [("Bench Press", 6), ("Squat", 8)])

    def test_no_top_set_when_the_last_main_set_was_not_done(self):
        ev = f.load_events(write_csv(self.dir, [
            "2026-01-01,Squat,Main,true;true;false,5;5;8,65.0;75.0;85.0,1,1,"], "t.csv"))[0]
        rows, _ = mu.counted_sets(ev, self.emap)
        self.assertEqual([r["top"] for r in rows], [False, False])

    def test_fractional_counting_session(self):
        res = mu.lens_session(self.ev, self.emap, date(2026, 1, 1))
        q = self.muscle(res, "quads")
        # squat 3 main + 1 joker (1.0) + deadlift bbb 3 (0.5) + leg extension 3 (1.0)
        self.assertEqual(q["sets"], 4 + 1.5 + 3)
        self.assertEqual(q["direct_sets"], 7)
        self.assertEqual(self.muscle(res, "calves")["sets"], 0)

    def test_program_window_and_per_week(self):
        res = mu.lens_program(self.ev, self.emap, weeks=4)
        # under a week of data: totals are reported as one week, never scaled up
        self.assertEqual(res["window"], {"start": "2026-01-01", "end": "2026-01-03",
                                         "weeks": 1.0, "sessions": 2, "partial_week": True})
        chest = self.muscle(res, "chest")
        self.assertEqual(chest["sets"], 3)
        self.assertEqual(chest["sets_per_week"], 3.0)
        with self.assertRaises(ValueError):
            mu.lens_program(self.ev, self.emap, weeks=0)
        with self.assertRaises(ValueError):
            mu.lens_program(self.ev, self.emap, as_of=date(2025, 12, 1))
        two = f.load_events(write_csv(self.dir, ROWS + [
            "2026-01-14,Bench Press,Main,true;true;true,5;5;6,45.0;52.5;60.0,1,2,"], "w.csv"))[0]
        res = mu.lens_program(two, self.emap, weeks=2)
        self.assertEqual((res["window"]["start"], res["window"]["weeks"]), ("2026-01-01", 2.0))
        self.assertEqual(self.muscle(res, "chest")["sets_per_week"], 3.0)
        self.assertEqual(len(res["muscles"]), 22)
        self.assertEqual(self.muscle(res, "neck")["sets_per_week"], 0)

    def test_lookup_ignores_case_spaces_hyphens(self):
        self.assertIn("deadlift", self.emap)
        rows, _ = mu.counted_sets(self.ev, self.emap)
        self.assertTrue(any(r["name"] == "Chest-Supported Row" for r in rows))

    def test_unmapped_stops_and_names_the_fix(self):
        p = write_csv(self.dir, ROWS + ["2026-01-03,Zercher Carry,,true,10,40.0,1,1,"], "b.csv")
        code, out, err = run_cli(p, "muscles", "--lens", "session")
        self.assertEqual(code, 1)
        self.assertIn("Zercher Carry", err)
        self.assertIn('map-set --state STATE.json "Zercher Carry"', err)
        code, out, _ = run_cli(p, "muscles", "--lens", "session", "--json")
        self.assertEqual(json.loads(out)["unmapped"], ["Zercher Carry"])
        # an unmapped exercise that was never done does not block anything
        p2 = write_csv(self.dir, ROWS + ["2026-01-03,Zercher Carry,,false,10,40.0,1,1,"], "c.csv")
        self.assertEqual(run_cli(p2, "muscles", "--lens", "session")[0], 0)
        # mapping it in the state file fixes it
        self.assertEqual(run_cli("map-set", "--state", self.state, "zercher carry", "abs=1",
                                 "forearms=0.5")[0], 0)
        code, out, _ = run_cli(p, "muscles", "--lens", "session", "--state", self.state, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(self.muscle(json.loads(out), "forearms")["sets"], 0.5 + 0.0)

    def test_other_set_types_reported_not_counted(self):
        p = write_csv(self.dir, ROWS + ["2026-01-03,Squat,Mystery,true,5,40.0,1,1,"], "d.csv")
        ev = f.load_events(p)[0]
        res = mu.lens_session(ev, self.emap)
        self.assertEqual(res["uncounted_other_sets"], 1)


class RecoveryTests(Base):
    def rec(self, as_of, state=None):
        return rc.lens_recovery(self.ev, self.emap, pm.resolve_params(state), state, as_of)

    def test_dose_sums_everything_in_the_session(self):
        rows, _ = mu.counted_sets(self.ev, self.emap)
        d = rc.daily_doses(rows, self.P)["quads"][date(2026, 1, 1)]["dose"]
        want = (2 * self.P["stim.main"] + self.P["stim.main_top"] + self.P["stim.joker"]
                + 3 * self.P["stim.bbb"] * 0.5 + 3 * self.P["stim.accessory"])
        self.assertAlmostEqual(d, want)

    def test_window_bands_and_states_at_boundaries(self):
        self.assertEqual(rc.window_days(1.5, self.P, "quads"), (0, 1, "band1"))
        self.assertEqual(rc.window_days(1.6, self.P, "quads"), (1, 2, "band2"))
        self.assertEqual(rc.window_days(99, self.P, "quads"), (3, 5, "band5"))
        q = lambda d: self.muscle(self.rec(d), "quads")  # noqa: E731
        x = q(date(2026, 1, 3))
        self.assertEqual((x["last_hit"], x["band"]), ("2026-01-01", "band3"))
        self.assertEqual((x["not_before"], x["recovered_by"]), ("2026-01-02", "2026-01-04"))
        self.assertEqual(x["state"], rc.UNCERTAIN)
        self.assertEqual(q(date(2026, 1, 4))["state"], rc.RECOVERED)
        self.assertEqual(q(date(2026, 1, 15))["state"], rc.RECOVERED)  # 14 days back is still recent
        ev1 = [e for e in self.ev if e["date"] == date(2026, 1, 1)]
        q1 = lambda d: self.muscle(rc.lens_recovery(ev1, self.emap, self.P, None, d), "quads")  # noqa: E731
        self.assertEqual(q1(date(2026, 1, 1))["state"], rc.NOT)        # before not_before
        self.assertEqual(q1(date(2026, 1, 2))["state"], rc.UNCERTAIN)  # on not_before
        self.assertEqual(q(date(2026, 1, 16))["state"], rc.UNTRAINED)  # over 14 days back
        self.assertEqual(self.muscle(self.rec(date(2026, 1, 3)), "neck")["state"], rc.UNTRAINED)

    def test_multiplier_lengthens_window_and_never_shortens_with_more_work(self):
        s = st.empty_state()
        st.set_param(s, "k", 1.5, "test", "2026-01-03")
        x = self.muscle(self.rec(date(2026, 1, 3), s), "quads")
        self.assertEqual((x["not_before"], x["recovered_by"], x["tuning"]),
                         ("2026-01-03", "2026-01-06", "adjusted"))
        more = f.load_events(write_csv(
            self.dir, ROWS + ["2026-01-01,Leg Extension,,true;true,12;12,30.0;30.0,1,1,"], "m.csv"))[0]
        y = self.muscle(rc.lens_recovery(more, self.emap, self.P, None, date(2026, 1, 3)), "quads")
        base = self.muscle(self.rec(date(2026, 1, 3)), "quads")
        self.assertGreaterEqual(y["recovered_by"], base["recovered_by"])
        self.assertGreater(y["dose"], base["dose"])

    def test_as_of_required_and_not_before_last_session(self):
        with self.assertRaises(ValueError):
            self.rec(None)
        with self.assertRaises(ValueError):
            self.rec(date(2026, 1, 2))
        code, _, err = run_cli(self.csv, "muscles", "--lens", "recovery")
        self.assertEqual(code, 1)
        self.assertIn("--as-of", err)

    def test_stated_rir_overrides_the_set_kind(self):
        s = st.empty_state()
        st.add_feedback(s, "rir", "2026-01-01", "Leg Extension", 4, "2026-01-01")
        rows, _ = mu.counted_sets(self.ev, self.emap)
        d0 = rc.daily_doses(rows, self.P)["quads"][date(2026, 1, 1)]["dose"]
        d1 = rc.daily_doses(rows, self.P, s)["quads"][date(2026, 1, 1)]["dose"]
        self.assertAlmostEqual(d0 - d1, 3 * (self.P["stim.accessory"] - self.P["rir.4_plus"]))

    def test_rir_does_not_touch_main_sets_of_the_same_lift(self):
        s = st.empty_state()
        st.add_feedback(s, "rir", "2026-01-01", "squat", 1, "2026-01-01")
        rows, _ = mu.counted_sets(self.ev, self.emap)
        used = {(x["kind"], x["stimulus_param"])
                for x in rc.daily_doses(rows, self.P, s)["adductors"][date(2026, 1, 1)]["sets"]}
        self.assertEqual(used, {("main", "stim.main"), ("main_top", "stim.main_top"),
                                ("joker", "rir.0_1")})

    def test_overlap_latest_window_end_wins(self):
        ev = f.load_events(write_csv(self.dir, [
            "2026-01-01,Leg Extension,,%s,%s,%s,-1,0," % (";".join(["true"] * 12),
                                                         ";".join(["12"] * 12), ";".join(["30.0"] * 12)),
            "2026-01-03,Leg Extension,,true,12,30.0,-1,0,"], "o.csv"))[0]
        x = self.muscle(rc.lens_recovery(ev, self.emap, self.P, None, date(2026, 1, 3)), "quads")
        self.assertEqual((x["last_hit"], x["dose"]), ("2026-01-03", 0.6))
        self.assertEqual((x["window_from_session"], x["window_dose"], x["recovered_by"]),
                         ("2026-01-01", 7.2, "2026-01-05"))
        self.assertEqual(x["state"], rc.UNCERTAIN)

    def test_next_lift_ignores_main_rows_that_were_not_done(self):
        ev = f.load_events(write_csv(self.dir, ROWS[:6] + [
            "2026-01-03,Bench Press,Main,false;false;false,5;5;6,45.0;52.5;60.0,1,1,",
            "2026-01-03,Chest-Supported Row,,true,12,50.0,1,1,"], "n.csv"))[0]
        ns = rc.lens_recovery(ev, self.emap, self.P, None, date(2026, 1, 3))["next_session"]
        self.assertEqual(ns["main_lift"], "Squat")
        self.assertIn("complete", ns["why"])  # bench was never done, so it is not "remaining"
        ev = f.load_events(write_csv(self.dir, ["2026-01-01,Row,,true,10,40.0,-1,0,"], "n2.csv"))[0]
        res = rc.lens_recovery(ev, self.emap, self.P, None, date(2026, 1, 1))
        self.assertFalse(res["next_session"]["available"])
        self.assertIn("not available", rc.text_next(res["next_session"]))
        self.assertNotIn("None", rc.text_recovery(res))

    def test_next_line_without_dates_or_mapping_says_so(self):
        ev = f.load_events(write_csv(self.dir, [
            "2026-01-01,Squat,Main,true;true;true,5;5;8,65.0;75.0;85.0,1,1,",
            "2026-01-03,Farmer Hold,Main,true;true;true,5;5;5,40.0;40.0;40.0,1,1,",
            "2026-01-05,Squat,Main,true;true;true,3;3;5,70.0;80.0;90.0,1,2,"], "n3.csv"))[0]
        emap = mu.resolve_map({"exercise_map": {"Farmer Hold": {"neck": 1.0}}})
        ns = rc.lens_recovery(ev, emap, self.P, None, date(2026, 1, 5))["next_session"]
        self.assertEqual(ns["main_lift"], "Farmer Hold")
        self.assertNotIn("None", rc.text_next(ns))
        del emap["farmerhold"]
        text = rc.text_next(rc.next_session(ev, emap, {m: {} for m in mu.MUSCLE_IDS}, self.P,
                                            date(2026, 1, 5)))
        self.assertIn("no muscle mapping for Farmer Hold", text)

    def test_unmatched_feedback_is_warned_about(self):
        s = st.empty_state()
        st.add_feedback(s, "rir", "2026-01-01", "Leg Extention", 2, "2026-01-01")
        st.add_feedback(s, "limited", "2031-05-05", "chest", 1, "2031-05-05")
        res = self.rec(date(2026, 1, 3), s)
        self.assertEqual(len(res["unmatched_feedback"]), 2)
        self.assertIn("WARNING: feedback rir:2026-01-01:legextention", rc.text_recovery(res))

    def test_param_back_at_default_is_not_adjusted_and_bands_are_cross_checked(self):
        s = st.empty_state()
        st.set_param(s, "k", 1.5, "x", "2026-01-03")
        st.set_param(s, "k", 1.0, "back", "2026-01-03")
        self.assertEqual(s["params"], {})
        self.assertEqual(self.muscle(self.rec(date(2026, 1, 3), s), "quads")["tuning"], "default")
        with self.assertRaises(ValueError):
            st.set_param(s, "band1.upto", 3.0, "x", "2026-01-03")  # 3.0 < band2.upto 3.5 is fine
            st.set_param(s, "band2.upto", 2.0, "x", "2026-01-03")  # but band2 below band1 is not

    def test_next_session_line(self):
        ns = self.rec(date(2026, 1, 3))["next_session"]
        self.assertTrue(ns["available"])
        # week complete (both lifts done in C1/W1): the lift that opened it comes next
        self.assertEqual((ns["main_lift"], ns["bbb_lift"]), ("Squat", "Dead Lift"))
        self.assertEqual([m["muscle"] for m in ns["muscles"]],
                         ["quads", "glutes", "hamstrings", "lower_back"])
        self.assertEqual(ns["valid_while_last_session_is"], "2026-01-03")
        self.assertLessEqual(ns["earliest"], ns["all_likely_recovered"])

    def test_tally_uses_the_state_going_into_the_session(self):
        s = st.empty_state()
        st.add_feedback(s, "limited", "2026-01-03", "chest", 2, "2026-01-03")
        st.add_feedback(s, "limited", "2026-01-03", "all", 0, "2026-01-03")
        t = self.rec(date(2026, 1, 3), s)["tally"]
        pts = {(p["muscle"], p["reported"]) for p in t["detail"]}
        self.assertEqual(pts, {("chest", 2), ("front_delts", 0)})
        self.assertEqual(t["table"][rc.UNTRAINED], {"limited": 1, "not_limited": 1})
        self.assertIn("not trained recently   1 / 1", rc.text_recovery(self.rec(date(2026, 1, 3), s)))


class StateAndCommandTests(Base):
    def test_feedback_is_idempotent_and_bumps_revision_only_on_change(self):
        args = ["feedback-add", "--state", self.state, "--measure", "limited",
                "--about-date", "2026-01-03", "--scope", "chest", "--value", "2", "--json"]
        r1 = json.loads(run_cli(*args)[1])
        r2 = json.loads(run_cli(*args)[1])
        self.assertEqual((r1["changed"], r1["revision"]), (True, 1))
        self.assertEqual((r2["changed"], r2["revision"]), (False, 1))
        s = st.load_state(self.state)
        self.assertEqual(len(s["feedback"]), 1)
        self.assertIn("limited:2026-01-03", s["answered"])

    def test_bad_inputs_are_refused(self):
        self.assertEqual(run_cli("feedback-add", "--state", self.state, "--measure", "limited",
                                 "--about-date", "2026-01-03", "--scope", "elbow", "--value", "2")[0], 1)
        self.assertEqual(run_cli("feedback-add", "--state", self.state, "--measure", "limited",
                                 "--about-date", "2026-01-03", "--scope", "chest", "--value", "7")[0], 1)
        self.assertEqual(run_cli("param-set", "--state", self.state, "k", "9", "--reason", "x")[0], 1)
        self.assertEqual(run_cli("param-set", "--state", self.state, "nope", "1", "--reason", "x")[0], 1)
        self.assertEqual(run_cli("map-set", "--state", self.state, "Thing", "elbow=1")[0], 1)
        self.assertFalse(os.path.exists(self.state))

    def test_param_set_is_logged_and_listed(self):
        code, out, _ = run_cli("param-set", "--state", self.state, "mult.quads", "1.25",
                               "--reason", "squat slower than bench", "--as-of", "2026-01-03")
        self.assertEqual(code, 0)
        s = st.load_state(self.state)
        self.assertEqual(s["param_log"][0]["old"], 1.0)
        out = run_cli("param-list", "--state", self.state)[1]
        self.assertIn("mult.quads", out)
        self.assertIn("squat slower than bench", out)

    def test_malformed_state_and_unwritable_path_exit_cleanly(self):
        for bad in ({"schema": 1, "exercise_map": []}, {"schema": 1, "params": []},
                    {"schema": 1, "feedback": [{"measure": "rir"}]},
                    {"schema": 1, "feedback": [{"id": "x", "measure": "limited", "about_date":
                                                "2026-01-03", "scope": "elbow", "value": 1}]},
                    {"schema": 1, "revision": "3"}, {"schema": 1, "dismissed": None}):
            with open(self.state, "w") as fh:
                json.dump(bad, fh)
            for cmd in ([self.csv, "muscles", "--lens", "recovery", "--as-of", "2026-01-03",
                         "--state", self.state], ["param-list", "--state", self.state],
                        ["unknown-dismiss", "--state", self.state, "x"],
                        [self.csv, "update", "--out-dir", self.dir, "--state", self.state,
                         "--state-revision", "1"]):
                code, _, err = run_cli(*cmd)
                self.assertEqual(code, 1, (bad, cmd))
                self.assertNotIn("Traceback", err, (bad, cmd))
        code, out, err = run_cli("map-set", "--state", os.path.join(self.dir, "nodir", "s.json"),
                                 "Foo", "chest=1", "--json")
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(out))
        self.assertEqual(run_cli("map-set", "--state", self.state + "2", " ", "chest=1")[0], 1)

    def test_feedback_remove_reopens_the_unknown(self):
        run_cli("feedback-add", "--state", self.state, "--measure", "rir", "--about-date",
                "2026-01-03", "--scope", "Military Press", "--value", "3")
        self.assertIn("rir:2026-01-03:militarypress", st.load_state(self.state)["answered"])
        self.assertEqual(run_cli("feedback-remove", "--state", self.state,
                                 "rir:2026-01-03:militarypress")[0], 0)
        s = st.load_state(self.state)
        self.assertEqual((s["feedback"], s["answered"], s["revision"]), ([], [], 2))
        self.assertEqual(run_cli("feedback-remove", "--state", self.state, "nope")[0], 1)

    def test_unknown_schema_is_an_error(self):
        with open(self.state, "w") as fh:
            json.dump({"schema": 99}, fh)
        code, _, err = run_cli(self.csv, "muscles", "--lens", "session", "--state", self.state)
        self.assertEqual(code, 1)
        self.assertIn("schema", err)

    def test_unknowns_rank_and_close(self):
        P, emap = self.P, self.emap
        items = rc.unknowns(self.ev, emap, P, None, date(2026, 1, 3), state_path=self.state)
        # the row fell short (50x12 50x12 50x10), so it is read as near failure, not asked about
        self.assertEqual([u["id"] for u in items],
                         ["limited:2026-01-03", "rir:2026-01-03:militarypress"])
        self.assertEqual(items[0]["id"], "limited:2026-01-03")
        # notes are listed for sessions after --notes-since
        items = rc.unknowns(self.ev, emap, P, None, date(2026, 1, 3), date(2025, 12, 31))
        self.assertEqual(items[0]["id"], "note:2026-01-01:legextension")
        two = f.load_events(write_csv(self.dir, [
            "2026-01-01,Squat,Main,true,5,60.0,1,1,main note",
            "2026-01-01,Squat,Joker sets,true,5,70.0,1,1,joker note"], "nn.csv"))[0]
        ids = [u["id"] for u in rc.unknowns(two, emap, P, None, date(2026, 1, 9))]
        self.assertEqual(ids, ["note:2026-01-01:squat:main", "note:2026-01-01:squat:jokersets"])
        # too long after the session: only notes remain
        late = rc.unknowns(self.ev, emap, P, None, date(2026, 1, 9), date(2025, 12, 31))
        self.assertEqual([u["type"] for u in late], ["note"])
        s = st.empty_state()
        st.add_feedback(s, "limited", "2026-01-03", "all", 0, "2026-01-03")
        left = rc.unknowns(self.ev, emap, P, s, date(2026, 1, 3))
        self.assertEqual([u["id"] for u in left], ["rir:2026-01-03:militarypress"])

    def test_explain_shows_sets_and_parameters(self):
        code, out, _ = run_cli(self.csv, "explain", "--muscle", "quads", "--as-of", "2026-01-03")
        self.assertEqual(code, 0)
        for needle in ("Leg Extension", "stim.main_top", "band3.hi", "mult.quads", "sets/week"):
            self.assertIn(needle, out)


class UpdateIntegrationTests(Base):
    def test_prev_supplies_the_stored_values(self):
        d = os.path.join(self.dir, "proj")
        os.makedirs(d)
        code, out, err = run_cli(self.csv, "update", "--as-of", "2026-01-03", "--prev", d)
        self.assertEqual(code, 0, err)
        self.assertNotIn("UNCHANGED", out)  # nothing stored yet
        code, out, _ = run_cli(self.csv, "update", "--as-of", "2026-01-04", "--prev", d)
        self.assertIn("UNCHANGED", out)
        # a new session: notes after the stored last session are listed, no UNCHANGED
        newer = write_csv(self.dir, ROWS + [
            "2026-01-05,Squat,Main,true;true;true,5;5;5,60.0;70.0;80.0,1,2,felt heavy"], "n.csv")
        code, out, _ = run_cli(newer, "update", "--as-of", "2026-01-05", "--prev", d)
        self.assertEqual(code, 0)
        self.assertNotIn("UNCHANGED", out)
        self.assertNotIn("NO NEW SESSIONS", out)
        self.assertIn("felt heavy", out)
        self.assertNotIn("quads were toast", out)  # before the stored last session
        # an export with fewer sessions than stored is refused
        code, _, err = run_cli(self.csv, "update", "--as-of", "2026-01-05", "--prev", d)
        self.assertNotEqual(code, 0)
        self.assertIn("expected at least 3", err + _)
        # a stored state revision with the state file gone is refused
        path = os.path.join(d, "muscles.csv")
        with open(path, encoding="utf-8") as fh:
            text = fh.read().replace("state_revision=none", "state_revision=2")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        code, out, err = run_cli(newer, "update", "--as-of", "2026-01-05", "--prev", d)
        self.assertNotEqual(code, 0)
        self.assertIn("state revision 2", out + err)

    def test_update_writes_muscle_files_and_guards_state(self):
        out_dir = os.path.join(self.dir, "stage")
        code, out, _ = run_cli(self.csv, "update", "--as-of", "2026-01-03", "--out-dir", out_dir)
        self.assertEqual(code, 0)
        self.assertIn("state: none", out)
        self.assertIn("Unknowns (2)", out)
        with open(os.path.join(out_dir, "muscles.csv"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertIn("last_session=2026-01-03", lines[1])
        self.assertIn("state_revision=none", lines[1])
        self.assertEqual(lines[4], ",".join(mc.MUSCLE_CSV_COLUMNS))
        self.assertEqual(len(lines), 5 + 22)
        with open(os.path.join(out_dir, "progress.md"), encoding="utf-8") as fh:
            self.assertIn("## Next session\nNext session: Squat + Dead Lift BBB.", fh.read())
        self.assertEqual(run_cli(self.csv, "report", "--as-of", "2026-01-03")[1],
                         open(os.path.join(out_dir, "progress.md"), encoding="utf-8").read())
        # the stored file expected revision 2; the state is missing, then too old
        code, _, err = run_cli(self.csv, "update", "--out-dir", out_dir, "--state", self.state,
                               "--state-revision", "2")
        self.assertEqual(code, 1)
        self.assertIn("REJECTED", err)
        run_cli("unknown-dismiss", "--state", self.state, "x")
        self.assertEqual(run_cli(self.csv, "update", "--out-dir", out_dir, "--state", self.state,
                                 "--state-revision", "2")[0], 1)
        run_cli("unknown-dismiss", "--state", self.state, "y")
        self.assertEqual(run_cli(self.csv, "update", "--as-of", "2026-01-03", "--out-dir", out_dir,
                                 "--state", self.state, "--state-revision", "2")[0], 0)

    def test_update_withholds_muscles_when_unmapped(self):
        p = write_csv(self.dir, ROWS + ["2026-01-03,Zercher Carry,,true,10,40.0,1,1,"], "b.csv")
        out_dir = os.path.join(self.dir, "stage")
        run_cli(self.csv, "update", "--as-of", "2026-01-03", "--out-dir", out_dir)
        self.assertTrue(os.path.exists(os.path.join(out_dir, "muscles.csv")))  # a stale one exists
        code, out, _ = run_cli(p, "update", "--as-of", "2026-01-03", "--out-dir", out_dir)
        self.assertEqual(code, 0)
        self.assertIn("MUSCLE OUTPUT WITHHELD", out)
        self.assertFalse(os.path.exists(os.path.join(out_dir, "muscles.csv")))
        self.assertTrue(os.path.exists(os.path.join(out_dir, "progress.md")))


class ShortfallTests(Base):
    def test_rep_shortfall_reads_as_near_failure(self):
        rows, _ = mu.counted_sets(self.ev, self.emap)
        short = rc.shortfalls(rows)
        self.assertIn(("2026-01-03", "chestsupportedrow"), short)
        self.assertNotIn(("2026-01-03", "militarypress"), short)  # 25x10 25x10: no shortfall
        doses = rc.daily_doses(rows, self.P)
        row_sets = [x for x in doses["lats"][date(2026, 1, 3)]["sets"]
                    if x["exercise"] == "Chest-Supported Row"]
        self.assertTrue(all(x["stimulus_param"] == "rir.0_1" and x["effort"].startswith("inferred")
                            for x in row_sets))
        # stated reps in reserve beat the inference
        s = st.empty_state()
        st.add_feedback(s, "rir", "2026-01-03", "Chest-Supported Row", 3, "2026-01-03")
        stated = [x for x in rc.daily_doses(rows, self.P, s)["lats"][date(2026, 1, 3)]["sets"]
                  if x["exercise"] == "Chest-Supported Row"]
        self.assertTrue(all(x["stimulus_param"] == "rir.2_3" for x in stated))

    def test_heavier_set_with_fewer_reps_is_not_a_shortfall(self):
        ev = f.load_events(write_csv(self.dir, [
            "2026-01-01,Squat,Main,true;true;true,5;5;5,60.0;70.0;80.0,1,1,",
            "2026-01-01,Row,,true;true;true,12;12;10,47.6;47.6;54.3,1,1,"], "h.csv"))[0]
        rows, _ = mu.counted_sets(ev, self.emap)
        self.assertEqual(rc.shortfalls(rows), {})


class MusclesCliTests(Base):
    def test_html_alone_and_date_misuse(self):
        out_html = os.path.join(self.dir, "m.html")
        code, out, _ = run_cli(self.csv, "muscles", "--html", out_html)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out_html))
        code, out, err = run_cli(self.csv, "muscles", "--lens", "recovery", "--date", "2026-01-03")
        self.assertNotEqual(code, 0)
        self.assertIn("--as-of", out + err)
        code, _, _ = run_cli(self.csv, "muscles")
        self.assertNotEqual(code, 0)


class RenderTests(Base):
    def test_every_muscle_has_a_region_coloured_from_the_data(self):
        allres = mc.build_all(self.ev, None, date(2026, 1, 3))
        html = render_html(allres)
        from five3one.render import _BACK, _FRONT
        self.assertEqual(set(_FRONT) | set(_BACK), set(mu.MUSCLE_IDS))
        self.assertEqual(html.count("<section>"), 3)
        self.assertIn("Quads: uncertain. Last hit 2026-01-01", html)
        self.assertIn('class="m s-unc"', html)
        self.assertIn("Chest: 3 sets (Bench Press x3)", html)
        self.assertNotIn("http", html.replace("http://www.w3.org", ""))  # self-contained

    def test_artwork_split_pieces_and_unique_clip_ids(self):
        import re
        from five3one.render import _pieces
        for view in ("front", "back"):
            for m, _, clip, seam in _pieces(view):
                self.assertTrue(m is None or m in mu.MUSCLE_IDS)
        html = render_html(mc.build_all(self.ev, None, date(2026, 1, 3)))
        ids = re.findall(r'<clipPath id="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        for m in ("front_delts", "side_delts", "rear_delts", "brachialis", "mid_back", "traps"):
            self.assertIn(mu.LABEL[m] + ":", html)


if __name__ == "__main__":
    unittest.main()
