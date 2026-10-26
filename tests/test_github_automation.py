from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ALLOWED_ACTIONS = {
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0",
    "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
    "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in loaded:
        loaded["on"] = loaded.pop(True)
    return loaded


def _steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def _run_scripts(workflow: dict[str, Any]) -> str:
    return "\n".join(str(step["run"]) for step in _steps(workflow) if "run" in step)


def test_ci_matrix_permissions_and_quality_commands() -> None:
    ci = _load_yaml(WORKFLOWS / "ci.yml")

    assert set(ci["on"]) == {"push", "pull_request"}
    assert ci["on"]["push"]["branches"] == ["main"]
    assert ci["on"]["pull_request"]["branches"] == ["main"]
    assert ci["permissions"] == {"contents": "read"}
    assert ci["concurrency"]["cancel-in-progress"] is True
    quality = ci["jobs"]["quality"]
    assert quality["runs-on"] == "ubuntu-latest"
    assert quality["strategy"]["matrix"]["python-version"] == ["3.11", "3.12", "3.13"]
    assert quality["name"] == "quality (${{ matrix.python-version }})"
    assert quality["env"]["QT_QPA_PLATFORM"] == "offscreen"
    commands = _run_scripts(ci)
    assert "apt-get install -y libegl1" in commands
    assert 'pip install -e ".[gui,dev]"' in commands
    assert "ruff check src tests scripts server.py client.py" in commands
    assert "ruff format --check src tests scripts server.py client.py" in commands
    assert "python -m pytest -q" in commands


def test_workflows_use_only_approved_immutable_github_actions() -> None:
    referenced: set[str] = set()
    for path in WORKFLOWS.glob("*.yml"):
        workflow = _load_yaml(path)
        referenced.update(str(step["uses"]) for step in _steps(workflow) if "uses" in step)

    assert referenced == ALLOWED_ACTIONS
    assert all(re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", action) for action in referenced)


def test_release_builds_all_platforms_and_only_tags_publish() -> None:
    release = _load_yaml(WORKFLOWS / "release.yml")

    assert release["on"]["push"]["tags"] == ["v*"]
    assert release["on"]["workflow_dispatch"] is None
    assert release["permissions"] == {"contents": "read"}
    build = release["jobs"]["build"]
    assert build["strategy"]["matrix"]["os"] == ["windows-latest", "macos-latest", "ubuntu-22.04"]
    assert build["runs-on"] == "${{ matrix.os }}"
    assert build["permissions"] == {"contents": "read"}
    release_job = release["jobs"]["release"]
    assert release_job["needs"] == "build"
    assert release_job["if"] == "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')"
    assert release_job["permissions"] == {"contents": "write"}

    commands = _run_scripts(release)
    for required in (
        "validate-tag",
        "pyside6-deploy",
        "validate-bundle",
        "--service --help",
        "sha256",
        "gh release view",
        "gh release create",
        "gh release upload",
        "--clobber",
    ):
        assert required in commands
    assert "gh release view" in commands and "||" in commands
    build_steps = build["steps"]
    assert any(
        step.get("if") == "runner.os == 'Linux'"
        and "apt-get install -y libegl1" in str(step.get("run", ""))
        and "python -m pip install -c packaging/constraints.txt patchelf" in str(step.get("run", ""))
        for step in build_steps
    )
    constraints = (ROOT / "packaging" / "constraints.txt").read_text(encoding="utf-8").splitlines()
    assert "patchelf==0.19.1.0" in constraints
    assert any(step.get("if") == "runner.os == 'Windows'" and step.get("shell") == "pwsh" for step in build_steps)
    assert any(step.get("if") == "runner.os != 'Windows'" and step.get("shell") == "bash" for step in build_steps)
    unix_archive = next(step for step in build_steps if step.get("id") == "archive_unix")
    assert 'runner.os }}" == "macOS"' in unix_archive["run"]
    assert "tar -czf" in unix_archive["run"]


def test_release_artifact_names_include_version_os_and_actual_architecture() -> None:
    release = _load_yaml(WORKFLOWS / "release.yml")
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")

    assert (
        "M3U8-Downloader-Pro-${{ steps.meta.outputs.version }}-${{ runner.os }}-${{ steps.bundle.outputs.architecture }}"
        in text
    )
    upload_steps = [
        step for step in _steps(release) if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(upload_steps) == 1
    assert upload_steps[0]["with"]["if-no-files-found"] == "error"
    assert upload_steps[0]["with"]["path"] == "release/*"


def test_dependabot_updates_python_and_actions_weekly() -> None:
    config = _load_yaml(ROOT / ".github" / "dependabot.yml")

    updates = config["updates"]
    assert {update["package-ecosystem"] for update in updates} == {"pip", "github-actions"}
    assert all(update["directory"] == "/" for update in updates)
    assert all(update["schedule"]["interval"] == "weekly" for update in updates)
    assert all(0 < update["open-pull-requests-limit"] <= 10 for update in updates)
