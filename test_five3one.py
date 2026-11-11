#!/usr/bin/env python3
"""Tests for five3one.py using small synthetic exports (no personal data).

Run: python3 -I test_five3one.py   (five3one.py must sit in the same folder)
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import five3one as f  # noqa: E402

HEADER = "Date,Name,Set,SetCompleted,Reps,Weights,CycleNr,WeekNr,Notes\n"


def write_csv(dirpath, name, rows):
    path = os.path.join(dirpath, name)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(HEADER + "".join(r + "\n" for r in rows))
    return path


def run_cli(*argv):
    p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "five3one.py"), *argv],
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()


class ParsingTests(Base):
    def test_parallel_arrays_and_multiline_notes(self):
        p = os.path.join(self.dir, "a.csv")
        with open(p, "w", newline="", encoding="utf-8") as fh:
            fh.write(HEADER)
            fh.write('2026-01-01,Squat,Main,true;true;false,5;3;1,60.0;70.0;80.0,1,1,"line one\n\nline two"\n')
        ev, errs, warns = f.load_events(p)
        self.assertEqual((errs, warns), ([], []))
        self.assertEqual([e["reps"] for e in ev], [5, 3, 1])
        self.assertEqual([e["completed"] for e in ev], [True, True, False])
        self.assertIn("line two", ev[0]["notes"])

    def test_mismatched_arrays_warn(self):
        p = write_csv(self.dir, "a.csv", ["2026-01-01,Row,,true;true,10;10;10,20.0;20.0;20.0,-1,0,"])
        _, errs, warns = f.load_events(p)
        self.assertEqual(errs, [])
        self.assertEqual(len(warns), 1)

    def test_epley(self):
        self.assertEqual(f.epley(100, 3), 110.0)
        self.assertIsNone(f.epley(None, 3))

    def test_name_drift_uses_most_recent_spelling(self):
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,hammer curl,,true,10,10.0,1,1,",
            "2026-01-05,Hammer Curl,,true,10,10.0,1,1,",
            "2026-01-09,hammer curl ,,true,10,10.0,1,1,"])
        ev, _, _ = f.load_events(p)
        self.assertEqual(len({e["key"] for e in ev}), 1)
        self.assertEqual(list(f.canonical_names(ev).values()), ["hammer curl"])

    def test_warmup_alone_does_not_make_a_main_lift(self):
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Warm up,true,5,40.0,1,1,",
            "2026-01-01,Squat,Main,true,5,60.0,1,1,",
            "2026-01-01,Hammer Curl,Warm up,true,10,5.0,1,1,"])
        ev, _, _ = f.load_events(p)
        self.assertEqual(f.main_lift_keys(ev), ["squat"])

    def test_same_day_duplicate_rows_keep_row_order(self):
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Main,true;true,5;3,60.0;70.0,1,1,",
            "2026-01-01,Squat,Main,true,1,80.0,1,1,"])
        ev, _, _ = f.load_events(p)
        sets = f.group_rows(ev)[0][3]
        self.assertEqual([s["weight"] for s in sets], [60.0, 70.0, 80.0])


class BlockTests(Base):
    def _events(self, gap):
        d2 = date.fromordinal(date(2026, 1, 1).toordinal() + gap).isoformat()
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Main,true,5,60.0,1,1,",
            "%s,Squat,Main,true,5,60.0,1,1," % d2])
        return f.load_events(p)[0]

    def test_gap_boundary(self):
        self.assertEqual(len(f.detect_blocks(self._events(20))), 1)
        self.assertEqual(len(f.detect_blocks(self._events(21))), 2)


class LiftResolutionTests(Base):
    def setUp(self):
        super().setUp()
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Main,true,5,60.0,1,1,",
            "2026-01-02,Front Squat,Main,true,5,40.0,1,1,"])
        self.ev = f.load_events(p)[0]

    def test_exact_beats_substring(self):
        self.assertEqual(f.resolve_lift(self.ev, "Squat"), "squat")
        self.assertEqual(f.resolve_lift(self.ev, "front"), "front squat")

    def test_unknown_lift_errors(self):
        with self.assertRaises(ValueError):
            f.resolve_lift(self.ev, "curl")


class StatusTests(Base):
    def test_position_comes_from_latest_main_session(self):
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Main,true,5,60.0,1,1,",
            "2026-01-03,Bench Press,Main,true,5,40.0,1,3,",
            "2026-01-05,Squat,Main,true,5,60.0,1,2,"])
        code, out, _ = run_cli(p, "status", "--as-of", "2026-01-06", "--json")
        data = json.loads(out)
        self.assertEqual((code, data["cycle"], data["week"]), (0, 1, 2))
        self.assertEqual(data["days_since_last_session"], 1)

    def test_stale_flag(self):
        p = write_csv(self.dir, "a.csv", ["2026-01-01,Squat,Main,true,5,60.0,1,1,"])
        data = json.loads(run_cli(p, "status", "--as-of", "2026-01-10", "--json")[1])
        self.assertTrue(data["stale"])


class TrainingMaxTests(Base):
    def test_tm_derived_from_week_percentages(self):
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Main,true;true;true,5;5;5,65.0;75.0;85.0,1,1,",
            "2026-01-03,Bench Press,Main,true;true;true;true,5;3;5;3,52.5;60.0;67.5;70.0,1,3,"])
        tms = json.loads(run_cli(p, "status", "--as-of", "2026-01-04", "--json")[1])["training_maxes"]
        self.assertEqual(tms["Squat"]["tm"], 100.0)
        self.assertEqual(tms["Bench Press"]["tm"], 70.0)  # extra 4th set ignored
        self.assertEqual(tms["Bench Press"]["week"], 3)

    def test_inconsistent_sets_are_unclear(self):
        p = write_csv(self.dir, "a.csv", ["2026-01-01,Squat,Main,true;true;true,5;5;5,40.0;75.0;85.0,1,1,"])
        code, out, _ = run_cli(p, "status", "--as-of", "2026-01-02")
        self.assertEqual(code, 0)
        self.assertIn("Squat unclear", out)

    def test_latest_session_wins_and_deload_ignored(self):
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Main,true;true;true,5;5;5,65.0;75.0;85.0,1,1,",
            "2026-01-08,Squat,Main,true;true;true,3;3;3,77.0;88.0;99.0,1,2,",
            "2026-01-15,Squat,Main,true;true;true,5;5;5,40.0;50.0;60.0,1,0,"])
        tms = json.loads(run_cli(p, "status", "--as-of", "2026-01-16", "--json")[1])["training_maxes"]
        self.assertEqual((tms["Squat"]["tm"], tms["Squat"]["week"]), (110.0, 2))


class WordingTests(Base):
    def test_unticked_sets_flagged_as_not_done(self):
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Main,true;true;true,5;5;5,65.0;75.0;85.0,1,1,",
            "2026-01-01,Dead Lift,Boring but BIG sets,true;false,10;10,50.0;50.0,1,1,"])
        out = run_cli(p, "status", "--as-of", "2026-01-02")[1]
        self.assertIn("not done (unticked) 50x10 (of 2 sets)", out)
        self.assertNotIn("not completed", out)


class ReportTests(Base):
    def setUp(self):
        super().setUp()
        self.csv = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Main,true;true;true,5;5;5,65.0;75.0;85.0,1,1,",
            "2026-01-01,Dead Lift,Boring but BIG sets,true;true,10;10,50.0;50.0,1,1,",
            "2026-01-03,Bench Press,Main,true;true;true,5;5;8,45.0;52.5;60.0,1,1,"])

    def test_report_equals_header_status_recap(self):
        out_path = os.path.join(self.dir, "progress.md")
        code, stdout, _ = run_cli(self.csv, "report", "--as-of", "2026-01-04", "--out", out_path)
        self.assertEqual(code, 0)
        self.assertIn("wrote", stdout)
        status = run_cli(self.csv, "status", "--as-of", "2026-01-04")[1]
        recap = run_cli(self.csv, "recap")[1]
        expected = (f.REPORT_HEADER % ("2026-01-03", "2026-01-04")
                    + "\n## Status\n```\n" + status + "```\n"
                    + "\n## Recap (14 days before last session)\n```\n" + recap + "```\n")
        with open(out_path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), expected)

    def test_report_prints_without_out(self):
        code, stdout, _ = run_cli(self.csv, "report", "--as-of", "2026-01-04")
        self.assertEqual(code, 0)
        self.assertTrue(stdout.startswith("# Progress\n"))
        self.assertIn("(last logged session 2026-01-03), as of 2026-01-04", stdout)


class UpdateTests(Base):
    def setUp(self):
        super().setUp()
        self.csv = write_csv(self.dir, "export.csv", [
            "2026-01-01,Squat,Main,true;true;true,5;5;5,65.0;75.0;85.0,1,1,",
            "2026-01-03,Bench Press,Main,true;true;true,5;5;8,45.0;52.5;60.0,1,1,"])
        self.out = os.path.join(self.dir, "stage")

    def test_update_writes_csv_and_report(self):
        code, stdout, _ = run_cli(self.csv, "update", "--as-of", "2026-01-04",
                                  "--out-dir", self.out, "--min-sessions", "2")
        self.assertEqual(code, 0)
        self.assertIn("VALID: 2 sessions", stdout)
        with open(self.csv, "rb") as a, open(os.path.join(self.out, "workouts.csv"), "rb") as b:
            self.assertEqual(a.read(), b.read())
        report = run_cli(self.csv, "report", "--as-of", "2026-01-04")[1]
        with open(os.path.join(self.out, "progress.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), report)

    def test_update_refuses_session_loss(self):
        code, _, err = run_cli(self.csv, "update", "--out-dir", self.out, "--min-sessions", "3")
        self.assertEqual(code, 1)
        self.assertIn("possible data loss", err)
        self.assertFalse(os.path.exists(os.path.join(self.out, "progress.md")))

    def test_update_works_piped_from_stdin(self):
        with open(os.path.join(HERE, "five3one.py"), encoding="utf-8") as fh:
            src = fh.read()
        p = subprocess.run([sys.executable, "-I", "-", self.csv, "update", "--as-of", "2026-01-04",
                            "--out-dir", self.out], input=src, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.out, "progress.md")))


class AdherenceTests(Base):
    def test_blank_completed_is_excluded_not_counted_as_missed(self):
        p = write_csv(self.dir, "a.csv", [
            "2026-01-01,Squat,Main,true;true,5;5,60.0;60.0,1,1,",
            "2026-01-02,Squat,Main,,5,60.0,1,1,"])
        data = json.loads(run_cli(p, "adherence", "--json")[1])
        self.assertEqual(data["main_lifts"]["sets"], 2)
        self.assertEqual(data["main_lifts"]["unknown_status"], 1)
        self.assertEqual(data["main_lifts"]["rate"], 1.0)


class CliTests(Base):
    def test_bad_date_arg_is_usage_error(self):
        p = write_csv(self.dir, "a.csv", ["2026-01-01,Squat,Main,true,5,60.0,1,1,"])
        self.assertEqual(run_cli(p, "session", "--date", "nope")[0], 2)

    def test_empty_csv_errors_cleanly(self):
        p = write_csv(self.dir, "a.csv", [])
        code, out, err = run_cli(p, "status")
        self.assertEqual(code, 1)
        self.assertIn("No data rows", err)

    def test_json_error_is_structured(self):
        p = write_csv(self.dir, "a.csv", ["2026-01-01,Squat,Main,true,5,60.0,1,1,"])
        code, out, _ = run_cli(p, "lift", "--name", "curl", "--json")
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(out))

    def test_last_zero_is_empty(self):
        p = write_csv(self.dir, "a.csv", ["2026-01-01,Squat,Main,true,5,60.0,1,1,"])
        data = json.loads(run_cli(p, "lift", "--name", "squat", "--last", "0", "--json")[1])
        self.assertEqual(data["main_sessions"], [])


class IngestTests(Base):
    def setUp(self):
        super().setUp()
        self.old = write_csv(self.dir, "old.csv", [
            "2026-01-01,Squat,Main,true,5,60.0,1,1,",
            "2026-01-03,Bench Press,Main,true,5,40.0,1,1,"])
        self.new = write_csv(self.dir, "new.csv", [
            "2026-01-01,Squat,Main,true,5,60.0,1,1,",
            "2026-01-03,Bench Press,Main,true,5,40.0,1,1,",
            "2026-01-05,Dead Lift,Main,true,5,80.0,1,1,"])

    def test_new_sessions_detected_and_written(self):
        out = os.path.join(self.dir, "out.csv")
        code, stdout, _ = run_cli(self.new, "ingest", "--stored", self.old, "--out", out, "--json")
        data = json.loads(stdout)
        self.assertEqual((code, data["valid"], data["new_sessions"]), (0, True, ["2026-01-05"]))
        with open(self.new, "rb") as a, open(out, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_missing_rows_rejected_and_not_written(self):
        out = os.path.join(self.dir, "out.csv")
        code, stdout, _ = run_cli(self.old, "ingest", "--stored", self.new, "--out", out, "--json")
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout)["valid"])
        self.assertFalse(os.path.exists(out))
        code, _, _ = run_cli(self.old, "ingest", "--stored", self.new, "--out", out, "--allow-missing")
        self.assertEqual(code, 0)

    def test_dry_run_writes_nothing(self):
        code, stdout, _ = run_cli(self.new, "ingest", "--stored", self.old)
        self.assertEqual(code, 0)
        self.assertIn("dry run", stdout)

    def test_bad_row_rejected(self):
        bad = write_csv(self.dir, "bad.csv", ["2026-13-45,Squat,Main,true,5,60.0,1,1,"])
        self.assertEqual(run_cli(bad, "ingest")[0], 1)

    def test_wrong_header_rejected(self):
        p = os.path.join(self.dir, "hdr.csv")
        with open(p, "w") as fh:
            fh.write("Date,Name,Set\n2026-01-01,Squat,Main\n")
        self.assertEqual(run_cli(p, "ingest")[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
