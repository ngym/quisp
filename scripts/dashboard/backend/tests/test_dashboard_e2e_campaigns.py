from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn

playwright = pytest.importorskip("playwright.sync_api")

from scripts.dashboard.backend.app import main
from scripts.dashboard.backend.app.models import SimTemplate
from scripts.dashboard.backend.tests.test_api_campaigns import FakeCampaignRunner


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _serve_app(app):
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            response = httpx.get(f"{url}/api/metrics", timeout=0.2)
            if response.status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("dashboard test server did not start")
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _install_profile_template(monkeypatch, root: Path):
    template_path = root / "quisp" / "simulations" / "two_nodes.ini"
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text("[Config two_node_MIM]\n", encoding="utf-8")

    def _templates(project_root=None):
        return [
            SimTemplate(
                template_id="quisp/simulations/two_nodes.ini",
                path=str(template_path),
                available_configs=["two_node_MIM"],
                description="mock",
                default_workdir=str(root),
                last_modified="1970-01-01T00:00:00Z",
            )
        ]

    def _template_with_configs(template_id_arg, project_root=None):
        assert template_id_arg == "quisp/simulations/two_nodes.ini"
        return {
            "path": template_path,
            "config_names": ["two_node_MIM"],
            "default_workdir": str(root),
        }

    monkeypatch.setattr(main, "list_templates", _templates)
    monkeypatch.setattr(main, "template_with_configs", _template_with_configs)


@pytest.mark.e2e
def test_experiments_workspace_preview_enqueue_and_view_run(page, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "SimulationRunner", FakeCampaignRunner)
    _install_profile_template(monkeypatch, tmp_path)
    app = main.create_app(log_dir=tmp_path / "runs", workspace_root=tmp_path, max_concurrent_runs=1)

    with _serve_app(app) as base_url:
        page.goto(base_url)

        workspace = page.locator('[data-testid="experiments-workspace"]')
        playwright.expect(workspace).to_be_visible()

        page.get_by_label("Experiment Profile").select_option("verify_two_node_setup")
        page.get_by_test_id("campaign-display-name").fill("E2E campaign")
        page.get_by_test_id("campaign-sweep-add").click()
        page.get_by_test_id("campaign-sweep-parameter").select_option("execution.seed_set")
        page.get_by_test_id("campaign-sweep-values").fill("1,2")
        page.get_by_test_id("campaign-preview-button").click()

        preview = page.get_by_test_id("campaign-preview")
        playwright.expect(preview).to_contain_text("2 runs")
        page.get_by_test_id("campaign-enqueue-button").click()

        tracker = page.get_by_test_id("campaign-tracker")
        playwright.expect(tracker).to_be_visible()
        playwright.expect(tracker).to_contain_text("E2E campaign")
        playwright.expect(tracker).to_contain_text("running")

        page.get_by_test_id("campaign-view-run").first.click()
        playwright.expect(page.locator("#topologyCanvas")).to_be_visible()
