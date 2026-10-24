"""The settings editor (IF-608, TICKETS.md plan note 42): every pipeline `config/*.yaml` file as a
form built from its `ideaforge.config` model, with the raw YAML as a fallback, and a history of
saves with a diff and a revert.

A save is validated by the file's config model first (and, for `models.yaml`, the `harness_*`
roles must stay as they are: `harness.config.json` has to match them, so they change only by
hand); an invalid save writes nothing. A form save is written with `ruamel.yaml` round-trip, so
the file's comments, key order and flow style stay. Saving a file `scripts/gen_agents.py` renders
the agents from (models, budget, rubric, domains) regenerates them, and a failed generation
restores the file. Saving is refused while a job is running, because a run snapshots the settings
at its start (`meta.json`). Every save is a `settings_history` row; a revert is itself a save.
`harness.config.json` stays out of the UI.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import importlib.util
import io
import os
import sqlite3
import threading
import types
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

import yaml
from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.scalarstring import ScalarString

from ideaforge import config, db

GEN_AGENTS_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gen_agents.py"
HARNESS_PREFIX = "harness_"  # models.yaml roles of the development harness, read-only here
_SAVE_LOCK = threading.Lock()  # one save at a time; gen_agents' stdout redirect is process-wide


@dataclass(frozen=True)
class SettingsFile:
    key: str
    title: str
    model: type[BaseModel]
    note: str
    gen_agents: bool  # scripts/gen_agents.py renders the agent files from it

    @property
    def name(self) -> str:
        return f"{self.key}.yaml"

    @property
    def path(self) -> Path:
        return config.CONFIG_DIR / self.name


FILES = {f.key: f for f in (
    SettingsFile(
        "models", "Models", config.ModelsConfig,
        "The model of each pipeline role. Saving regenerates the agent files (scripts/gen_agents.py)."
        " The harness_* roles are development settings: harness.config.json must use the same values,"
        " so they are changed by hand, not here.",
        True,
    ),
    SettingsFile(
        "budget", "Budget presets", config.BudgetConfig,
        "Each preset's search, fetch, output and debate limits, and the default preset."
        " Saving regenerates the agent files, whose prompts state the default preset's limits.",
        True,
    ),
    SettingsFile("founder", "Founder", config.FounderConfig, "The founder constraints every new idea starts from.", False),
    SettingsFile("report", "Report", config.ReportConfig, "The languages of the report and of the business-plan draft.", False),
    SettingsFile(
        "rubric", "Rubric", config.RubricConfig,
        "Dimension weights (they must sum to 1.0), research questions, evidence rules and kill triggers."
        " Saving regenerates the research agents.",
        True,
    ),
    SettingsFile(
        "domains", "Domains", config.DomainsConfig,
        "The official-source allow-list and each dimension's preferred domains. Saving regenerates the research agents.",
        True,
    ),
    SettingsFile(
        "finland", "Finland hints", config.FinlandConfig,
        "Hints to verify, not facts: research agents confirm each value on its verify_url and cite that page,"
        " never this file.",
        False,
    ),
)}


class SettingsError(Exception):
    """A save that wrote nothing; `errors` are shown with the form, `output` is gen_agents' output."""

    def __init__(self, errors: list[str], output: str = ""):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.output = output


class SaveRefused(SettingsError):
    """A save refused because a job is running."""


@dataclass
class Saved:
    entry_id: int | None  # the settings_history row; None when nothing changed
    output: str = ""  # scripts/gen_agents.py's output


@dataclass(frozen=True)
class FormField:
    """One form input: a scalar, or a list of scalars (one per line), at `path` in the file."""

    name: str
    path: tuple[str | int, ...]
    label: str
    kind: Literal["text", "textarea", "number", "select", "lines", "readonly"]
    value: str
    choices: tuple[str, ...] = ()
    help: str = ""


def settings_file(key: str) -> SettingsFile:
    try:
        return FILES[key]
    except KeyError:
        raise LookupError(f"no settings file {key!r}") from None


# ---------------------------------------------------------------- YAML round trip


class _Representer(RoundTripRepresenter):
    pass


# The files spell an empty value `null`; ruamel would write nothing after the colon.
_Representer.add_representer(type(None), lambda r, _: r.represent_scalar("tag:yaml.org,2002:null", "null"))


def _yaml() -> YAML:
    y = YAML()
    y.Representer = _Representer
    y.preserve_quotes = True
    y.width = 4096  # never re-wrap a long line
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def read(f: SettingsFile) -> str:
    return f.path.read_text(encoding="utf-8")


def load(text: str) -> Any:
    return _yaml().load(text)


def dump(doc: Any) -> str:
    out = io.StringIO()
    _yaml().dump(doc, out)
    return out.getvalue()


def header(text: str) -> str:
    """The comment block a file starts with: what the file is for, in its own words."""
    lines = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        lines.append(line.lstrip("#").strip())
    return "\n".join(lines).strip()


def _comment(node: Any, key: Any) -> str:
    """The end-of-line comment after `key` in a ruamel mapping (first line only), or ''."""
    ca = getattr(node, "ca", None)
    tokens = ca.items.get(key) if ca is not None else None
    token = tokens[2] if tokens and len(tokens) > 2 else None
    text = getattr(token, "value", "") or ""
    first = text.split("\n", 1)[0].strip()
    return first.lstrip("#").strip()


# ---------------------------------------------------------------- form fields


def _unwrap(ann: Any) -> Any:
    if get_origin(ann) in (Union, types.UnionType):
        args = [a for a in get_args(ann) if a is not type(None)]
        return args[0] if len(args) == 1 else None
    return ann


def _sub(ann: Any, key: str | int) -> Any:
    """The annotation of `key` inside `ann` (a config model, dict or list type), or None."""
    ann = _unwrap(ann)
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        field = ann.model_fields.get(key) if isinstance(key, str) else None
        return field.annotation if field else None
    origin = get_origin(ann)
    if origin is dict:
        return get_args(ann)[1]
    if origin is list:
        return get_args(ann)[0]
    return None


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _field(f: SettingsFile, doc: Any, value: Any, path: tuple, labels: tuple[str, ...], ann: Any, help: str) -> FormField:
    name = "f:" + "/".join(str(p) for p in path)
    label = " › ".join(labels)
    ann = _unwrap(ann)
    if f.key == "models" and path[:1] == ("roles",) and str(path[-1]).startswith(HARNESS_PREFIX):
        return FormField(name, path, label, "readonly", _scalar_text(value), help=help or "development setting")
    if isinstance(value, list):
        return FormField(name, path, label, "lines", "\n".join(_scalar_text(v) for v in value), help=help or "one per line")
    if isinstance(value, bool):
        return FormField(name, path, label, "select", _scalar_text(value), ("true", "false"), help)
    if f.key == "budget" and path == ("default_preset",):
        return FormField(name, path, label, "select", str(value), tuple(doc.get("presets") or ()), help)
    if get_origin(ann) is Literal:
        return FormField(name, path, label, "select", _scalar_text(value), tuple(str(c) for c in get_args(ann)), help)
    if isinstance(value, int | float):
        return FormField(name, path, label, "number", _scalar_text(value), help=help)
    text = _scalar_text(value)
    return FormField(name, path, label, "textarea" if "\n" in text else "text", text, help=help)


def fields(key: str, doc: Any = None, overrides: Mapping[str, str] | None = None) -> list[FormField]:
    """The form of a settings file: one field per scalar or list of scalars, labelled by its
    path (a list item by its `id` when it has one), with the file's end-of-line comment as help.
    `overrides` (a refused form, as posted) replaces the shown values."""
    f = settings_file(key)
    doc = load(read(f)) if doc is None else doc
    out: list[FormField] = []

    def walk(node: Any, path: tuple, labels: tuple[str, ...], ann: Any, help: str) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                walk(v, (*path, k), (*labels, str(k)), _sub(ann, k), _comment(node, k))
        elif isinstance(node, list) and any(isinstance(i, Mapping | list) for i in node):
            for i, item in enumerate(node):
                item_label = str(item["id"]) if isinstance(item, Mapping) and "id" in item else f"#{i + 1}"
                walk(item, (*path, i), (*labels, item_label), _sub(ann, i), "")
        else:
            out.append(_field(f, doc, node, path, labels, ann, help))

    walk(doc, (), (), f.model, "")
    if overrides:
        out = [replace(fl, value=overrides[fl.name]) if fl.kind != "readonly" and fl.name in overrides else fl for fl in out]
    return out


def _get(doc: Any, path: tuple) -> Any:
    for p in path:
        doc = doc[p]
    return doc


def _number(raw: str) -> int | float:
    text = raw.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"{raw!r} is not a number") from None


def _parse(field: FormField, old: Any, raw: str) -> Any:
    raw = raw.replace("\r\n", "\n")
    if field.kind == "lines":
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if field.kind == "select" and isinstance(old, bool):
        if raw not in ("true", "false"):
            raise ValueError(f"{raw!r} is not true or false")
        return raw == "true"
    if field.kind == "number":
        value = _number(raw)
        return float(value) if isinstance(old, float) else value
    if old is None:  # an empty hint value: a number when it reads as one
        if not raw.strip():
            return None
        try:
            return _number(raw)
        except ValueError:
            return raw
    if field.kind == "textarea" and isinstance(old, str) and old.endswith("\n") and not raw.endswith("\n"):
        raw += "\n"
    return raw


def form_text(key: str, form: Mapping[str, str]) -> str:
    """The file with the posted form's values put in (ruamel round-trip, so comments stay); a
    field the form does not post keeps its value, and an unparsable value is an error."""
    f = settings_file(key)
    doc = load(read(f))
    errors = []
    for field in fields(key, doc):
        if field.kind == "readonly" or field.name not in form:
            continue
        old = _get(doc, field.path)
        try:
            new = _parse(field, old, form[field.name])
        except ValueError as e:
            errors.append(f"{field.label}: {e}")
            continue
        if isinstance(old, list):
            if list(old) != new:
                old[:] = new  # in place: the sequence keeps its flow style and comments
            continue
        if new == old and isinstance(new, bool) == isinstance(old, bool):
            continue  # untouched: the scalar keeps its spelling (0.10 stays 0.10)
        parent, k = _get(doc, field.path[:-1]), field.path[-1]
        # a ScalarString keeps its literal block (`|`) or its quoting
        parent[k] = type(old)(new) if isinstance(old, ScalarString) and isinstance(new, str) else new
    if errors:
        raise SettingsError(errors)
    return dump(doc)


def summary(key: str, doc: Any) -> str | None:
    """A line the form shows above the fields: the rubric's weight sum."""
    if key != "rubric":
        return None
    try:
        total = sum(float(d["weight"]) for d in doc["dimensions"])
    except (KeyError, TypeError, ValueError):
        return None
    return f"The dimension weights sum to {total:.4g} (they must sum to 1.0)."


# ---------------------------------------------------------------- saving


def job_refusal() -> str | None:
    """Why no settings may be saved now (a running job), or None."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT job_id, kind, run_id FROM jobs WHERE status='running' ORDER BY job_id LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    what = f"/{row['kind']}" + (f" {row['run_id']}" if row["run_id"] else "")
    return (
        f"job {row['job_id']} ({what}) is running, and a run snapshots the settings at its start (meta.json);"
        " wait for it to finish or cancel it"
    )


def _error(err: dict) -> str:
    loc = ".".join(str(p) for p in err["loc"])
    return f"{loc}: {err['msg']}" if loc else err["msg"]


def check(f: SettingsFile, text: str, current: str) -> None:
    """Raise SettingsError unless `text` is a valid `f`; for models.yaml the harness_* roles
    must equal the `current` file's."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SettingsError([f"not valid YAML: {e}"]) from None
    try:
        f.model.model_validate(data)
    except ValidationError as e:
        raise SettingsError([_error(err) for err in e.errors()]) from None
    if f.key == "models":
        old, new = (yaml.safe_load(current) or {}).get("roles", {}), data["roles"]
        changed = sorted(r for r in {*old, *new} if r.startswith(HARNESS_PREFIX) and old.get(r) != new.get(r))
        if changed:
            raise SettingsError([
                f"roles.{r} is a development setting (harness.config.json must use the same value): change it by"
                " hand, not here" for r in changed
            ])


def normalize(text: str) -> str:
    """A browser posts a textarea with CRLF line ends; the files use LF and end with one."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text if not text or text.endswith("\n") else text + "\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def gen_agents() -> tuple[bool, str]:
    """Run scripts/gen_agents.py in this process (so it sees this root); (ok, its output)."""
    spec = importlib.util.spec_from_file_location("ideaforge_gen_agents", GEN_AGENTS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            spec.loader.exec_module(module)
            code = module.main([])
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if not isinstance(e.code, int | None):
            out.write(f"{e.code}\n")
    except Exception as e:  # noqa: BLE001 — a failed generation restores the file and shows why
        code = 1
        out.write(f"{type(e).__name__}: {e}\n")
    return code in (0, None), out.getvalue().strip()


def save(key: str, text: str) -> Saved:
    """Validate and write `text` as the settings file `key`, regenerate the agents when the file
    feeds them (restoring the file if that fails) and record the save in `settings_history`."""
    f = settings_file(key)
    text = normalize(text)
    with _SAVE_LOCK:
        why = job_refusal()
        if why:
            raise SaveRefused([f"Saving is refused: {why}."])
        before = read(f)
        check(f, text, before)
        if text == before:
            return Saved(None)
        _write(f.path, text)
        config.reload()
        output = ""
        if f.gen_agents:
            ok, output = gen_agents()
            if not ok:
                _write(f.path, before)
                config.reload()
                gen_agents()  # the agents of the restored file, in case some were written
                raise SettingsError([f"scripts/gen_agents.py failed, so config/{f.name} was restored."], output)
        with db.session() as conn:
            cur = conn.execute(
                "INSERT INTO settings_history(ts, file, sha_before, sha_after, content_before, content_after)"
                " VALUES (?,?,?,?,?,?)",
                (db.now(), f.name, sha(before), sha(text), before, text),
            )
        return Saved(cur.lastrowid, output)


# ---------------------------------------------------------------- history


def history(key: str) -> list[sqlite3.Row]:
    f = settings_file(key)
    with db.session() as conn:
        return conn.execute(
            "SELECT id, ts, sha_before, sha_after FROM settings_history WHERE file=? ORDER BY id DESC", (f.name,)
        ).fetchall()


def last_saves() -> dict[str, str]:
    """File name → the time of its latest save."""
    with db.session() as conn:
        return {r["file"]: r["ts"] for r in conn.execute("SELECT file, MAX(ts) AS ts FROM settings_history GROUP BY file")}


def entry(key: str, entry_id: int) -> sqlite3.Row:
    f = settings_file(key)
    with db.session() as conn:
        row = conn.execute("SELECT * FROM settings_history WHERE id=? AND file=?", (entry_id, f.name)).fetchone()
    if row is None:
        raise LookupError(f"no save {entry_id} of config/{f.name}")
    return row


def diff(row: sqlite3.Row) -> list[tuple[str, str]]:
    """The save as a unified diff: (css class, line) pairs."""
    lines = difflib.unified_diff(
        row["content_before"].splitlines(keepends=True), row["content_after"].splitlines(keepends=True),
        fromfile=f"{row['file']} {row['sha_before'][:12]}", tofile=f"{row['file']} {row['sha_after'][:12]}",
    )
    out = []
    for line in lines:
        line = line.rstrip("\n")
        kind = (
            "meta" if line.startswith(("+++", "---")) else "hunk" if line.startswith("@@")
            else "add" if line.startswith("+") else "del" if line.startswith("-") else ""
        )
        out.append((kind, line))
    return out


def revert(key: str, entry_id: int) -> Saved:
    """Put back the file as it was before save `entry_id`: a validated save like any other."""
    return save(key, entry(key, entry_id)["content_before"])
