"""The local web UI (D-008, TICKETS.md plan note 36): a FastAPI app with Jinja2 templates.

`create_app()` builds it for the project root the rest of the package uses (`config.ROOT`, set
by `IDEAFORGE_ROOT`); `python -m ideaforge.web` serves it on 127.0.0.1 only. Pages read through
the pipeline modules and never write a run's artefacts: the runs dashboard (`dashboard`), the
run page with its tabs (`run_detail`, the debate tab `debate_view`), and the review form, review
trend and run comparison (`reviews`). Review scores are the only run data a page writes, through
the same `review.store` as `/status --review`.

Pipeline control (`control`, IF-607): the new-idea and new-version forms, the run actions and the
eval action queue jobs (`ideaforge.jobs`); the jobs page shows them with a live log tail, cancel
and retry. The server runs one background worker from start to shutdown. A request that changes
anything (POST) is refused unless it comes from this UI: a loopback Host and, when the browser
names one, the same Origin, so another web page cannot start jobs through the browser.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import get_args
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from ideaforge import config, db, debate, jobs, report, review, scoring, status
from ideaforge.schemas import KILL_TRIGGERS, VerdictLabel
from ideaforge.web import control, dashboard, debate_view, reviews, run_detail
from ideaforge.web.run_detail import ClaimFilters, NotFound

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
WEB_DIR = Path(__file__).resolve().parent

NAV = (
    ("runs", "Runs", "/"),
    ("new", "New idea", "/new"),
    ("reviews", "Reviews", "/reviews"),
    ("compare", "Compare", "/compare"),
    ("jobs", "Jobs", "/jobs"),
    ("settings", "Settings", "/settings"),
)
VERDICTS = (*get_args(VerdictLabel), dashboard.UNSCORED)
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def foreign_request(headers: Mapping[str, str]) -> str | None:
    """Why a state-changing request does not come from this UI, or None. The Host must be a
    loopback name (a DNS-rebound page has its own name there) and an Origin, when the browser
    sends one, must be this same host."""
    host = headers.get("host", "")
    hostname = urlsplit(f"//{host}").hostname or ""
    if hostname not in {h.strip("[]") for h in LOCAL_HOSTS}:
        return f"Host {host!r} is not this machine"
    origin = headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != host:
        return f"Origin {origin!r} is not this UI"
    if headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return "a cross-site request"
    return None


def create_app(root: Path | None = None, *, worker_poll: float = jobs.POLL_SECONDS) -> FastAPI:
    """The app for `root` (default `config.ROOT`). The pipeline modules fix their paths at
    import, so a different root must be chosen with `IDEAFORGE_ROOT` before starting; a root
    that disagrees with `config.ROOT` is refused rather than half-applied. The background
    worker runs between the app's startup and shutdown (its lifespan)."""
    root = (root or config.ROOT).resolve()
    if root != config.ROOT.resolve():
        raise ValueError(f"root {root} is not the project root {config.ROOT}; set IDEAFORGE_ROOT instead")
    db.init()
    worker = control.Worker(poll=worker_poll)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        worker.start()
        try:
            yield
        finally:
            await run_in_threadpool(worker.stop)

    app = FastAPI(title="Ideaforge", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.root = root
    app.state.worker = worker

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next):
        if request.method not in SAFE_METHODS:
            why = foreign_request(request.headers)
            if why:
                return PlainTextResponse(f"refused: {why}", status_code=403)
        return await call_next(request)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")
    templates.env.globals["link_claims"] = run_detail.link_claims
    templates.env.globals["models_text"] = review.models_text

    def page(request: Request, name: str, active: str, status_code: int = 200, **context) -> HTMLResponse:
        return templates.TemplateResponse(
            request, name,
            {"nav": NAV, "active": active, "dev_marker": jobs.dev_marker_refusal(), **context},
            status_code=status_code,
        )

    @app.exception_handler(NotFound)
    def not_found(request: Request, exc: NotFound) -> HTMLResponse:
        return page(request, "not_found.html", "runs", status_code=404, message=str(exc))

    def run_page(request: Request, r: run_detail.Run, tab: str, status_code: int = 200, **context) -> HTMLResponse:
        stage = run_detail.TAB_STAGE.get(tab)
        return page(
            request, f"run_{tab}.html", "runs", status_code=status_code,
            run=r, tabs=run_detail.TABS, tab=tab,
            stage=stage, stage_status=run_detail.stage_status(r.run_id, stage) if stage else None,
            actions=control.run_actions(r.run_id, r.in_db, r.has_dir), run_actions=control.RUN_ACTIONS,
            run_jobs=control.open_jobs(r.run_id),
            **context,
        )

    def dashboard_page(
        request: Request, verdict: str = "", idea: str = "", status_code: int = 200, **context
    ) -> HTMLResponse:
        rows = dashboard.run_rows()
        shown = dashboard.filter_rows(rows, verdict=verdict or None, idea=idea or None)
        return page(
            request, "dashboard.html", "runs", status_code=status_code,
            lineages=dashboard.lineages(shown),
            mismatch=dashboard.mismatch(),
            total=len(rows),
            shown=len(shown),
            verdicts=VERDICTS,
            ideas=sorted({r.idea_id for r in rows}),
            verdict=verdict,
            idea=idea,
            eval_refusal=control.eval_refusal(),
            **context,
        )

    @app.get("/", response_class=HTMLResponse)
    def runs_dashboard(request: Request, verdict: str = "", idea: str = "") -> HTMLResponse:
        return dashboard_page(request, verdict, idea)

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

    # ------------------------------------------------------------ pipeline control (IF-607)

    async def form_fields(request: Request) -> tuple[dict[str, str], list[str]]:
        form = await request.form()
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
        return fields, [v for v in form.getlist("kill_trigger_overrides") if isinstance(v, str)]

    def idea_page(
        request: Request, form: control.IdeaForm, *, parent: run_detail.Run | None = None,
        errors: list[str] = (), status_code: int = 200,
    ) -> HTMLResponse:
        context = dict(
            form=form, errors=list(errors), goals=control.GOALS, presets=sorted(config.budget().presets),
            kill_triggers=KILL_TRIGGERS, run_to=control.RUN_TO, founder=config.founder(),
        )
        if parent is None:
            return page(request, "new_idea.html", "new", status_code=status_code, **context)
        return run_page(request, parent, "version", status_code=status_code, **context)

    def queued(ids: list[int]) -> RedirectResponse:
        worker.ensure()
        return RedirectResponse(f"/jobs/{ids[0]}", status_code=303)

    @app.get("/new", response_class=HTMLResponse)
    def new_idea(request: Request) -> HTMLResponse:
        return idea_page(request, control.IdeaForm.defaults())

    @app.post("/new", response_model=None)
    async def submit_idea(request: Request) -> HTMLResponse | RedirectResponse:
        """Create the run from the form (new_run.py --intake) and queue its chain; a refused form
        creates and queues nothing and is shown again with every reason."""
        form = control.IdeaForm.from_fields(*await form_fields(request))
        try:
            _, ids = await run_in_threadpool(control.start_idea, control.check_idea(form))
        except control.FormError as e:
            return idea_page(request, form, errors=e.errors, status_code=400)
        return queued(ids)

    def refused(r: run_detail.Run, action: str) -> str | None:
        return control.run_actions(r.run_id, r.in_db, r.has_dir)[action]

    @app.get("/runs/{run_id}/version", response_class=HTMLResponse)
    def version_form(request: Request, run_id: str) -> HTMLResponse:
        r = run_detail.run(run_id)
        why = refused(r, "version")
        if why:
            return run_page(request, r, "stages", status_code=409, action_error=f"New version refused: {why}.",
                            stages=run_detail.stage_rows(run_id), markers=run_detail.markers(r.run_dir))
        return idea_page(request, control.IdeaForm.for_version(run_id), parent=r)

    @app.post("/runs/{run_id}/version", response_model=None)
    async def submit_version(request: Request, run_id: str) -> HTMLResponse | RedirectResponse:
        """The run's next version (new_run.py --from with the form's intake), then its chain."""
        r = run_detail.run(run_id)
        form = control.IdeaForm.from_fields(*await form_fields(request))
        why = refused(r, "version")
        if why:
            return idea_page(request, form, parent=r, errors=[f"New version refused: {why}."], status_code=409)
        try:
            _, ids = await run_in_threadpool(control.start_idea, control.check_idea(form), run_id)
        except control.FormError as e:
            return idea_page(request, form, parent=r, errors=e.errors, status_code=400)
        return queued(ids)

    @app.post("/runs/{run_id}/actions/{action}", response_model=None)
    def run_action(request: Request, run_id: str, action: str) -> HTMLResponse | RedirectResponse:
        """Resume validate, synthesize or debate: one job on the run, when its state allows it."""
        r = run_detail.run(run_id)
        if action not in ("validate", "synthesize", "debate"):
            raise NotFound(f"unknown run action {action!r}")
        why = refused(r, action)
        if why is None:
            try:
                return queued(jobs.enqueue(action, run_id))
            except jobs.JobError as e:
                why = str(e)
        label = dict(control.RUN_ACTIONS)[action]
        return run_page(request, r, "stages", status_code=409, action_error=f"{label} refused: {why}.",
                        stages=run_detail.stage_rows(run_id), markers=run_detail.markers(r.run_dir))

    @app.post("/eval", response_model=None)
    async def run_eval(request: Request) -> HTMLResponse | RedirectResponse:
        """Queue /eval [--limit N] [--fresh] (the golden set), unless an eval job is still open."""
        fields, _ = await form_fields(request)
        why = control.eval_refusal()
        if why:
            return dashboard_page(request, status_code=409, eval_error=f"Eval refused: {why}.")
        try:
            args = control.check_eval(fields.get("limit", ""), fields.get("fresh", ""))
        except control.FormError as e:
            return dashboard_page(request, status_code=400, eval_error="; ".join(e.errors))
        return queued(jobs.enqueue("eval", args=args))

    def job_page(request: Request, job_id: int, status_code: int = 200, **context) -> HTMLResponse:
        try:
            row = jobs.get(job_id)
        except jobs.JobError as e:
            raise NotFound(str(e)) from None
        log = control.log_chunk(job_id)
        return page(
            request, "job.html", "jobs", status_code=status_code,
            job=control.job_row(row), chain=control.chain(job_id), log=log,
            started_at=row["started_at"], finished_at=row["finished_at"], exit_code=row["exit_code"],
            log_path=row["log_path"], worker=worker.state(), finished=row["status"] in jobs.FINISHED,
            **context,
        )

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs_page(request: Request) -> HTMLResponse:
        return page(request, "jobs.html", "jobs", rows=control.job_rows(), worker=worker.state(),
                    finished=jobs.FINISHED)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: int) -> HTMLResponse:
        return job_page(request, job_id)

    @app.get("/jobs/{job_id}/log")
    def job_log(job_id: int, offset: int | None = None) -> JSONResponse:
        """The log bytes after `offset` (the poller sends the offset it got last), as text."""
        try:
            chunk = control.log_chunk(job_id, offset)
            job_status = jobs.get(job_id)["status"]
        except jobs.JobError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        return JSONResponse({**asdict(chunk), "status": job_status}, headers={"Cache-Control": "no-store"})

    @app.post("/jobs/{job_id}/cancel", response_model=None)
    def cancel_job(request: Request, job_id: int) -> HTMLResponse | RedirectResponse:
        try:
            jobs.cancel(job_id)
        except jobs.JobError as e:
            return job_page(request, job_id, status_code=409, error=f"Cancel refused: {e}.")
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/retry", response_model=None)
    def retry_job(request: Request, job_id: int) -> HTMLResponse | RedirectResponse:
        try:
            ids = jobs.retry(job_id)
        except jobs.JobError as e:
            return job_page(request, job_id, status_code=409, error=f"Retry refused: {e}.")
        return queued(ids)

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request) -> HTMLResponse:
        return page(request, "placeholder.html", "settings", title="Settings", ticket="IF-608")

    return app
