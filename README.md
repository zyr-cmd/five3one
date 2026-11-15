# five3one

Stdlib-only CLI for reading Five3One (5/3/1 BBB) CSV exports. Usage and CSV quirks are in the package docstring (`five3one/__init__.py`).

Install a pinned commit and run:

```
pip install git+https://github.com/zyr-cmd/five3one@COMMIT
python3 -m five3one CSV COMMAND [options]
```

Muscle map: three lenses (program, session, recovery), a state file for mappings, tuning and feedback, and an HTML body diagram. Design in `docs/PLAN.md`; evidence for the recovery parameters in `docs/SOURCES.md`.

Run tests from the repo root: `python3 -m pytest` (no personal data; synthetic fixtures).
