"""The local web UI (D-008, TICKETS.md plan note 36): a FastAPI app with Jinja2 templates.

`create_app()` builds it for the project root the rest of the package uses (`config.ROOT`, set
by `IDEAFORGE_ROOT`); `python -m ideaforge.web` serves it on 127.0.0.1 only. Pages read through
the pipeline modules and never write a run's artefacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ideaforge import config, db
from ideaforge.schemas import VerdictLabel
from ideaforge.web import dashboard

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
WEB_DIR = Path(__file__).resolve().parent

NAV = (("runs", "Runs", "/"), ("jobs", "Jobs", "/jobs"), ("settings", "Settings", "/settings"))
VERDICTS = (*get_args(VerdictLabel), dashboard.UNSCORED)


def create_app(root: Path | None = None) -> FastAPI:
    """The app for `root` (default `config.ROOT`). The pipeline modules fix their paths at
    import, so a different root must be chosen with `IDEAFORGE_ROOT` before starting; a root
    that disagrees with `config.ROOT` is refused rather than half-applied."""
    root = (root or config.ROOT).resolve()
    if root != config.ROOT.resolve():
        raise ValueError(f"root {root} is not the project root {config.ROOT}; set IDEAFORGE_ROOT instead")
    db.init()

    app = FastAPI(title="Ideaforge", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.root = root
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")

    def page(request: Request, name: str, active: str, **context) -> HTMLResponse:
        return templates.TemplateResponse(request, name, {"nav": NAV, "active": active, **context})

    @app.get("/", response_class=HTMLResponse)
    def runs_dashboard(request: Request, verdict: str = "", idea: str = "") -> HTMLResponse:
        rows = dashboard.run_rows()
        shown = dashboard.filter_rows(rows, verdict=verdict or None, idea=idea or None)
        return page(
            request, "dashboard.html", "runs",
            lineages=dashboard.lineages(shown),
            mismatch=dashboard.mismatch(),
            total=len(rows),
            shown=len(shown),
            verdicts=VERDICTS,
            ideas=sorted({r.idea_id for r in rows}),
            verdict=verdict,
            idea=idea,
        )

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request) -> HTMLResponse:
        return page(request, "placeholder.html", "jobs", title="Jobs", ticket="IF-607")

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request) -> HTMLResponse:
        return page(request, "placeholder.html", "settings", title="Settings", ticket="IF-608")

    return app
