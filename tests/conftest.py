import sys
from pathlib import Path

import pytest

from ideaforge import config

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"

sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An isolated project root: runs/, cache/, a temp DB and no dev marker.

    config/, prompts/ and agent_templates/ still point at the real repo.
    """
    root = tmp_path / "proj"
    (root / "runs").mkdir(parents=True)
    (root / "cache").mkdir()
    monkeypatch.setattr(config, "ROOT", root)
    monkeypatch.setattr(config, "RUNS_DIR", root / "runs")
    monkeypatch.setattr(config, "CACHE_DIR", root / "cache")
    monkeypatch.setattr(config, "DEV_MARKER", root / ".ideaforge-dev")
    monkeypatch.setenv("IDEAFORGE_DB", str(root / "test.db"))
    monkeypatch.delenv("IDEAFORGE_RUN_ID", raising=False)
    return root


@pytest.fixture
def active_run(project):
    """A run directory registered as the active run."""
    from ideaforge import runs

    run_id = "20261023-120000-test-idea"
    runs.create_run_dir(run_id, "test idea")
    runs.set_active(run_id)
    return project / "runs" / run_id
