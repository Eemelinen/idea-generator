"""Review scores and run comparison in the UI (IF-606), through the IF-504 functions.

The review form turns its fields into the `section=score[:note]` entries `/status --review`
takes and stores them with `review.store`, so both write the same `reviews` rows; the trend page
shows `review.trend_data()`, which `/status --reviews` prints, and the compare page shows
`status.score_diff`, which `/status --diff` prints.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ideaforge import db, review, runs
from ideaforge.report import REPORT


def entries(form: Mapping[str, str]) -> list[str]:
    """The form's `score_<section>` / `note_<section>` fields as review entries; a section without
    a score is left out (it keeps its earlier score), and so is its note."""
    out = []
    for section in review.SECTIONS:
        score = (form.get(f"score_{section}") or "").strip()
        if not score:
            continue
        note = " ".join((form.get(f"note_{section}") or "").split())
        out.append(f"{section}={score}:{note}" if note else f"{section}={score}")
    return out


def unreviewable(run_id: str, in_db: bool) -> str | None:
    """Why the run cannot be reviewed yet, as `review.store` would refuse it; None when it can."""
    if not in_db:
        return f"run {run_id} is not in the database, so it cannot be reviewed"
    if not (runs.run_dir(run_id) / REPORT).is_file():
        return f"run {run_id} has no {REPORT} to review yet; run /synthesize {run_id} first"
    return None


@dataclass
class Choice:
    run_id: str
    title: str
    scored: bool  # has a 04_scores.json


def choices() -> list[Choice]:
    """Every run in the database, newest first, for the compare form."""
    with db.session() as conn:
        rows = conn.execute("SELECT run_id, idea_text FROM runs ORDER BY created_at DESC, run_id DESC").fetchall()
    result = []
    for r in rows:
        text = r["idea_text"].strip()
        try:
            scored = (runs.run_dir(r["run_id"]) / "04_scores.json").is_file()
        except ValueError:
            scored = False
        result.append(Choice(r["run_id"], text.splitlines()[0] if text else "(no idea text)", scored))
    return result
