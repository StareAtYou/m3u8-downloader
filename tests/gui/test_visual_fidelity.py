from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QImage

from scripts.capture_ui_reference import DEFAULT_REFERENCE, capture_ui_reference, main


def test_capture_entry_point_writes_normalized_visual_evidence(tmp_path: Path) -> None:
    output = tmp_path / "implementation.png"
    comparison = tmp_path / "comparison.png"
    detail = tmp_path / "detail-comparison.png"

    assert (
        main(
            [
                "--output",
                str(output),
                "--comparison-output",
                str(comparison),
                "--detail-comparison-output",
                str(detail),
                "--width",
                "1440",
                "--height",
                "1024",
            ]
        )
        == 0
    )

    implementation_image = QImage(str(output))
    comparison_image = QImage(str(comparison))
    detail_image = QImage(str(detail))
    assert not implementation_image.isNull()
    assert (implementation_image.width(), implementation_image.height()) == (1440, 1024)
    assert comparison_image.width() == 1440
    assert comparison_image.height() == 2048
    assert detail_image.width() == 1440
    assert detail_image.height() > 0
    assert all(path.stat().st_size > 10_000 for path in (output, comparison, detail))


def test_capture_is_fixture_only_warning_free_and_geometry_deterministic(tmp_path: Path) -> None:
    first = capture_ui_reference(
        output=tmp_path / "first.png",
        reference=DEFAULT_REFERENCE,
        comparison_output=tmp_path / "first-comparison.png",
        detail_comparison_output=tmp_path / "first-detail.png",
        width=1440,
        height=1024,
    )
    second = capture_ui_reference(
        output=tmp_path / "second.png",
        reference=DEFAULT_REFERENCE,
        comparison_output=tmp_path / "second-comparison.png",
        detail_comparison_output=tmp_path / "second-detail.png",
        width=1440,
        height=1024,
    )

    assert first["row_count"] == 6
    assert first["current_index"] == 1
    assert first["state_tones"] == {"blue", "amber", "purple", "red", "green"}
    assert first["route_tones"] == {"blue", "purple"}
    assert first["fixture_only"] is True
    assert first["warnings"] == []
    assert first["geometry"] == second["geometry"]
    assert (tmp_path / "first.png").read_bytes() == (tmp_path / "second.png").read_bytes()


def test_capture_cli_destroys_qml_before_bridge_without_shutdown_warnings(tmp_path: Path) -> None:
    root = Path(__file__).parents[2]
    command = [
        sys.executable,
        "scripts/capture_ui_reference.py",
        "--output",
        str(tmp_path / "implementation.png"),
        "--reference",
        str(DEFAULT_REFERENCE),
        "--comparison-output",
        str(tmp_path / "comparison.png"),
        "--detail-comparison-output",
        str(tmp_path / "detail.png"),
        "--width",
        "1440",
        "--height",
        "1024",
    ]
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    result = subprocess.run(
        command,
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
