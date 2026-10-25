from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.release_tools import (
    discover_qml_files,
    executable_stem_from_spec,
    load_project_version,
    locate_bundle,
    normalize_architecture,
    qml_files_from_spec,
    validate_bundle,
    validate_release_tag,
)

ROOT = Path(__file__).parents[1]


def test_project_version_and_release_tag_must_match() -> None:
    version = load_project_version(ROOT / "pyproject.toml")

    assert version == "0.2.0"
    validate_release_tag("v0.2.0", version)
    for invalid in ("0.2.0", "v0.2", "v0.2.1", "release-0.2.0", "v0.2.0-rc1"):
        with pytest.raises(ValueError):
            validate_release_tag(invalid, version)


def test_deploy_spec_lists_every_qml_resource() -> None:
    discovered = discover_qml_files(ROOT)

    assert "m3u8_downloader/gui/qml/theme/qmldir" in discovered
    assert "m3u8_downloader/gui/qml/components/StyledTextField.qml" in discovered
    assert qml_files_from_spec(ROOT / "pysidedeploy.spec") == discovered


def test_deploy_spec_executable_stem_matches_entry_point() -> None:
    assert executable_stem_from_spec(ROOT / "pysidedeploy.spec") == "gui_entry"


@pytest.mark.parametrize(
    ("machine", "expected"),
    [("arm64", "arm64"), ("aarch64", "arm64"), ("AMD64", "x64"), ("x86_64", "x64")],
)
def test_architecture_label_uses_runner_machine(machine: str, expected: str) -> None:
    assert normalize_architecture(machine) == expected


def test_unknown_architecture_is_rejected() -> None:
    with pytest.raises(ValueError, match="不支持的架构"):
        normalize_architecture("mips64")


def _write_bundle_resources(bundle_root: Path) -> None:
    qml = bundle_root / "m3u8_downloader" / "gui" / "qml" / "Main.qml"
    plugin = bundle_root / "PySide6" / "Qt" / "plugins" / "platforms" / "platform.bin"
    qml.parent.mkdir(parents=True)
    plugin.parent.mkdir(parents=True)
    qml.write_text("import QtQuick", encoding="utf-8")
    plugin.write_bytes(b"plugin")


@pytest.mark.parametrize("system", ["Windows", "Linux"])
def test_locate_and_validate_standalone_bundle(tmp_path: Path, system: str) -> None:
    bundle = tmp_path / "M3U8DownloaderPro.dist"
    executable = bundle / ("gui_entry.exe" if system == "Windows" else "gui_entry.bin")
    executable.parent.mkdir()
    executable.write_bytes(b"executable")
    _write_bundle_resources(bundle)

    assert locate_bundle(tmp_path, system) == (bundle, executable)
    validate_bundle(bundle, executable)


def test_locate_and_validate_macos_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "M3U8DownloaderPro.app"
    executable = bundle / "Contents" / "MacOS" / "gui_entry"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"executable")
    _write_bundle_resources(bundle)

    assert locate_bundle(tmp_path, "macOS") == (bundle, executable)
    validate_bundle(bundle, executable)


def test_locate_bundle_rejects_missing_or_ambiguous_outputs(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        locate_bundle(tmp_path, "Linux")

    (tmp_path / "one.dist").mkdir()
    (tmp_path / "two.dist").mkdir()
    with pytest.raises(RuntimeError, match="唯一"):
        locate_bundle(tmp_path, "Linux")


def test_validate_bundle_requires_executable_qml_and_platform_plugin(tmp_path: Path) -> None:
    bundle = tmp_path / "M3U8DownloaderPro.dist"
    executable = bundle / "gui_entry.bin"
    executable.parent.mkdir()

    with pytest.raises(FileNotFoundError, match="可执行"):
        validate_bundle(bundle, executable)

    executable.write_bytes(b"executable")
    with pytest.raises(FileNotFoundError, match="Main.qml"):
        validate_bundle(bundle, executable)

    qml = bundle / "gui" / "qml" / "Main.qml"
    qml.parent.mkdir(parents=True)
    qml.write_text("import QtQuick", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="platforms"):
        validate_bundle(bundle, executable)


def test_release_tools_cli_prints_machine_readable_bundle_paths(tmp_path: Path) -> None:
    bundle = tmp_path / "M3U8DownloaderPro.dist"
    executable = bundle / "gui_entry.bin"
    executable.parent.mkdir()
    executable.write_bytes(b"executable")
    _write_bundle_resources(bundle)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_tools.py",
            "validate-bundle",
            "--dist",
            str(tmp_path),
            "--system",
            "Linux",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert f"bundle={bundle}" in result.stdout
    assert f"executable={executable}" in result.stdout
