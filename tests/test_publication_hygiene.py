from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_publication import scan_paths

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("content", "rule"),
    [
        ("path=/Users/alice/Downloads", "posix-user-path"),  # publication-scan: allow-test-fixture
        ("path=/home/alice/Downloads", "posix-user-path"),  # publication-scan: allow-test-fixture
        (r"path=C:\Users\alice\Downloads", "windows-user-path"),  # publication-scan: allow-test-fixture
        (r"path=C:\\Users\\alice\\Downloads", "windows-user-path"),  # publication-scan: allow-test-fixture
        ("contact=alice@private.example", "email"),  # publication-scan: allow-test-fixture
        ("endpoint=10.2.3.4", "private-ip"),  # publication-scan: allow-test-fixture
        ("endpoint=172.20.1.2", "private-ip"),  # publication-scan: allow-test-fixture
        ("endpoint=192.168.1.2", "private-ip"),  # publication-scan: allow-test-fixture
        ("-----BEGIN PRIVATE KEY-----", "private-key"),  # publication-scan: allow-test-fixture
        ("token=ghp_abcdefghijklmnopqrstuvwxyz123456", "github-token"),  # publication-scan: allow-test-fixture
        ("token=github_pat_abcdefghijklmnopqrstuvwxyz_123456", "github-token"),  # publication-scan: allow-test-fixture
    ],
)
def test_scan_detects_sensitive_text(tmp_path: Path, content: str, rule: str) -> None:
    target = tmp_path / "settings.txt"
    target.write_text(content, encoding="utf-8")

    findings = scan_paths(tmp_path, [Path("settings.txt")])

    assert [(finding.path.as_posix(), finding.rule) for finding in findings] == [("settings.txt", rule)]


@pytest.mark.parametrize(
    "path",
    [
        "movie.mp4",
        "segment.ts",
        "secret.pem",
        "identity.key",
        "certificate.p12",
        "certificate.pfx",
        "history.bundle",
        "docs/superpowers/plan.md",
        "design-qa.md",
    ],
)
def test_scan_rejects_forbidden_public_paths_without_opening_them(tmp_path: Path, path: str) -> None:
    findings = scan_paths(tmp_path, [Path(path)])

    assert len(findings) == 1
    assert findings[0].rule == "forbidden-path"


def test_scan_allows_approved_identity_loopback_and_marked_test_fixture(tmp_path: Path) -> None:
    target = tmp_path / "safe.txt"
    target.write_text(
        "39252862+StareAtYou@users.noreply.github.com\n"
        "noreply@github.com\n"
        "127.0.0.1 localhost ::1\n"
        "token=ghp_abcdefghijklmnopqrstuvwxyz123456  # publication-scan: allow-test-fixture\n"
        "ordinary source text",
        encoding="utf-8",
    )

    assert scan_paths(tmp_path, [Path("safe.txt")]) == []


def test_scan_checks_printable_image_metadata(tmp_path: Path) -> None:
    image = tmp_path / "preview.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\nmetadata:/Users/alice/Downloads\x00pixels"  # publication-scan: allow-test-fixture
    )

    findings = scan_paths(tmp_path, [Path("preview.png")])

    assert [(finding.path.as_posix(), finding.rule) for finding in findings] == [("preview.png", "posix-user-path")]


def test_cli_reads_nul_manifest_and_does_not_echo_sensitive_value(tmp_path: Path) -> None:
    target = tmp_path / "config.txt"
    target.write_text("owner=alice@private.example", encoding="utf-8")  # publication-scan: allow-test-fixture
    manifest = tmp_path / "tracked.paths"
    manifest.write_bytes(b"config.txt\0")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_publication.py"),
            "--root",
            str(tmp_path),
            "--paths-from",
            str(manifest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "config.txt:1: email" in result.stdout
    assert "alice@private.example" not in result.stdout  # publication-scan: allow-test-fixture


def test_scanner_rule_definitions_and_marked_fixtures_do_not_self_report() -> None:
    paths = [Path("scripts/check_publication.py"), Path("tests/test_publication_hygiene.py")]

    assert scan_paths(ROOT, paths) == []
