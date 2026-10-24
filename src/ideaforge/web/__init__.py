"""The local web UI (D-008, TICKETS.md plan note 36): a FastAPI app with Jinja2 templates.

`create_app()` builds it for the project root the rest of the package uses (`config.ROOT`, set
by `IDEAFORGE_ROOT`); `python -m ideaforge.web` serves it on 127.0.0.1 only. Pages read through
the pipeline modules and never write a run's artefacts: the runs dashboard (`dashboard`), the
run page with its tabs (`run_detail`, the debate tab `debate_view`), and the review form, review
trend and run comparison (`reviews`). Review scores are the only thing a page writes, through
the same `review.store` as `/status --review`.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ideaforge import config, db, debate, report, review, scoring, status
from ideaforge.schemas import VerdictLabel
from ideaforge.web import dashboard, debate_view, reviews, run_detail
from ideaforge.web.run_detail import ClaimFilters, NotFound

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
WEB_DIR = Path(__file__).resolve().parent

NAV = (
    ("runs", "Runs", "/"),
    ("reviews", "Reviews", "/reviews"),
    ("compare", "Compare", "/compare"),
    ("jobs", "Jobs", "/jobs"),
    ("settings", "Settings", "/settings"),
)
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
    templates.env.globals["link_claims"] = run_detail.link_claims
    templates.env.globals["models_text"] = review.models_text

    def page(request: Request, name: str, active: str, status_code: int = 200, **context) -> HTMLResponse:
        return templates.TemplateResponse(
            request, name, {"nav": NAV, "active": active, **context}, status_code=status_code
        )

    @app.exception_handler(NotFound)
    def not_found(request: Request, exc: NotFound) -> HTMLResponse:
        return page(request, "not_found.html", "runs", status_code=404, message=str(exc))

    def run_page(request: Request, r: run_detail.Run, tab: str, **context) -> HTMLResponse:
        stage = run_detail.TAB_STAGE.get(tab)
        return page(
            request, f"run_{tab}.html", "runs",
            run=r, tabs=run_detail.TABS, tab=tab,
            stage=stage, stage_status=run_detail.stage_status(r.run_id, stage) if stage else None,
            **context,
        )

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

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_stages(request: Request, run_id: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        return run_page(
            request, r, "stages",
            stages=run_detail.stage_rows(run_id), markers=run_detail.markers(r.run_dir),
        )

    @app.get("/runs/{run_id}/idea", response_class=HTMLResponse)
    def run_idea(request: Request, run_id: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        return run_page(request, r, "idea", idea=run_detail.idea(r.run_dir))

    @app.get("/runs/{run_id}/claims", response_class=HTMLResponse)
    def run_claims(
        request: Request, run_id: str, dimension: str = "", verification: str = "", source_type: str = "",
        flag: str = "",
    ) -> HTMLResponse:
        r = run_detail.run(run_id)
        ledger = run_detail.ledger(run_id, r.run_dir)
        filters = ClaimFilters(dimension, verification, source_type, flag)
        return run_page(
            request, r, "claims",
            ledger=ledger, by_id=ledger.by_id(), filters=filters,
            shown=run_detail.filter_claims(ledger.claims, filters),
            options=run_detail.claim_options(ledger.claims),
        )

    @app.get("/runs/{run_id}/scores", response_class=HTMLResponse)
    def run_scores(request: Request, run_id: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        ledger = run_detail.ledger(run_id, r.run_dir)
        return run_page(
            request, r, "scores",
            scores=run_detail.scores(r.run_dir, ledger.claims), known=set(ledger.by_id()),
        )

    @app.get("/runs/{run_id}/economics", response_class=HTMLResponse)
    def run_economics(request: Request, run_id: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        ledger = run_detail.ledger(run_id, r.run_dir)
        return run_page(
            request, r, "economics",
            scores=run_detail.scores(r.run_dir, ledger.claims), known=set(ledger.by_id()),
        )

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    def run_report(request: Request, run_id: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        path = r.run_dir / report.REPORT
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() and not path.is_symlink() else None
        return run_page(
            request, r, "report",
            report_name=report.REPORT, html=None if text is None else run_detail.render_markdown(text),
        )

    @app.get("/runs/{run_id}/usage", response_class=HTMLResponse)
    def run_usage(request: Request, run_id: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        view = run_detail.usage_view(run_id, r.run_dir, db.stages(run_id)) if r.has_dir else None
        return run_page(request, r, "usage", usage=view)

    @app.get("/runs/{run_id}/files", response_class=HTMLResponse)
    def run_files(request: Request, run_id: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        return run_page(request, r, "files", files=run_detail.list_files(r.run_dir))

    @app.get("/runs/{run_id}/files/{path:path}", response_class=HTMLResponse)
    def run_file(request: Request, run_id: str, path: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        file = run_detail.safe_file(r.run_dir, path)
        return run_page(
            request, r, "file", path=path, size=file.stat().st_size, text=run_detail.file_text(file),
        )

    @app.get("/runs/{run_id}/raw/{path:path}")
    def run_raw(run_id: str, path: str) -> FileResponse:
        """The file as a download, never rendered: research pages may hold anything."""
        file = run_detail.safe_file(run_detail.run(run_id).run_dir, path)
        return FileResponse(
            file, media_type="application/octet-stream", filename=file.name,
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.get("/runs/{run_id}/debate", response_class=HTMLResponse)
    def run_debate(request: Request, run_id: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        ledger = run_detail.ledger(run_id, r.run_dir)
        return run_page(
            request, r, "debate",
            view=debate_view.debate_view(run_id, r.run_dir, r.in_db, ledger.by_id()),
            known=set(ledger.by_id()), min_agree=debate.CONFORMITY_MIN_AGREE,
        )

    def review_page(request: Request, r: run_detail.Run, **context) -> HTMLResponse:
        return run_page(
            request, r, "review",
            sections=review.SECTIONS, stored=review.stored(r.run_id) if r.in_db else {},
            unreviewable=reviews.unreviewable(r.run_id, r.in_db), **context,
        )

    @app.get("/runs/{run_id}/review", response_class=HTMLResponse)
    def run_review(request: Request, run_id: str, stored: str = "") -> HTMLResponse:
        # ?stored=1 follows a stored POST (redirected, so a reload does not resubmit the form)
        r = run_detail.run(run_id)
        return review_page(request, r, message="Review scores stored." if stored == "1" else None)

    @app.post("/runs/{run_id}/review", response_model=None)
    async def store_review(request: Request, run_id: str) -> HTMLResponse | RedirectResponse:
        """Store the form's scores with `review.store` (as /status --review); a bad entry or a
        run without a report stores nothing and shows why."""
        r = run_detail.run(run_id)
        form = await request.form()
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        try:
            review.store(run_id, reviews.entries(fields))
        except (review.ReviewError, LookupError) as e:
            return review_page(request, r, status_code=400, error=str(e))
        return RedirectResponse(f"/runs/{run_id}/review?stored=1", status_code=303)

    @app.get("/reviews", response_class=HTMLResponse)
    def review_trend(request: Request) -> HTMLResponse:
        return page(request, "reviews.html", "reviews", trend=review.trend_data())

    @app.get("/compare", response_class=HTMLResponse)
    def compare(request: Request, a: str = "", b: str = "") -> HTMLResponse:
        diff = error = None
        if a and b:
            try:
                diff = status.score_diff(a, b)
            except (LookupError, ValueError) as e:
                error = str(e)
        elif a or b:
            error = "choose two runs"
        return page(
            request, "compare.html", "compare",
            choices=reviews.choices(), a=a, b=b, diff=diff, error=error, cap=f"{scoring.CAP:g}",
            status_code=400 if error and a and b else 200,
        )

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request) -> HTMLResponse:
        return page(request, "placeholder.html", "jobs", title="Jobs", ticket="IF-607")

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request) -> HTMLResponse:
        return page(request, "placeholder.html", "settings", title="Settings", ticket="IF-608")

    return app
