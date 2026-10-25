from __future__ import annotations

import argparse
import configparser
import platform
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import tomllib

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_version(path: Path) -> str:
    with path.open("rb") as source:
        project = tomllib.load(source)["project"]
    version = project.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("pyproject.toml 中缺少有效的稳定版本号")
    return version


def validate_release_tag(tag: str, version: str) -> None:
    expected = f"v{version}"
    if tag != expected:
        raise ValueError(f"版本标签必须为 {expected}，实际为 {tag}")


def discover_qml_files(root: Path) -> set[str]:
    source_root = root / "src"
    qml_root = source_root / "m3u8_downloader" / "gui" / "qml"
    return {
        path.relative_to(source_root).as_posix()
        for path in qml_root.rglob("*")
        if path.is_file() and (path.suffix == ".qml" or path.name == "qmldir")
    }


def qml_files_from_spec(path: Path) -> set[str]:
    config = configparser.ConfigParser(interpolation=None)
    config.read(path, encoding="utf-8")
    raw = config.get("qt", "qml_files", fallback="")
    return {item.strip() for item in raw.split(",") if item.strip()}


def executable_stem_from_spec(path: Path) -> str:
    config = configparser.ConfigParser(interpolation=None)
    config.read(path, encoding="utf-8")
    input_file = config.get("app", "input_file", fallback="").strip()
    stem = Path(input_file).stem
    if not stem:
        raise ValueError("pysidedeploy.spec 中缺少有效的 app.input_file")
    return stem


def normalize_architecture(machine: str) -> str:
    normalized = machine.strip().lower()
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    if normalized in {"amd64", "x86_64"}:
        return "x64"
    raise ValueError(f"不支持的架构：{machine}")


def locate_bundle(
    dist_dir: Path,
    system: str,
    executable_stem: str | None = None,
) -> tuple[Path, Path]:
    executable_stem = executable_stem or executable_stem_from_spec(PROJECT_ROOT / "pysidedeploy.spec")
    normalized_system = system.strip().lower()
    if normalized_system in {"macos", "darwin"}:
        candidates = sorted(dist_dir.glob("*.app"))
        suffix = Path("Contents") / "MacOS" / executable_stem
    else:
        candidates = sorted(dist_dir.glob("*.dist"))
        suffix = Path(f"{executable_stem}.exe" if normalized_system == "windows" else f"{executable_stem}.bin")
    if not candidates:
        raise FileNotFoundError(f"在 {dist_dir} 中未找到打包产物")
    if len(candidates) != 1:
        raise RuntimeError(f"打包目录必须只有唯一产物，实际为 {len(candidates)} 个")
    bundle = candidates[0]
    return bundle, bundle / suffix


def validate_bundle(bundle_root: Path, executable: Path) -> None:
    if not executable.is_file():
        raise FileNotFoundError(f"未找到可执行文件：{executable}")
    if not any(path.is_file() for path in bundle_root.rglob("Main.qml")):
        raise FileNotFoundError(f"{bundle_root} 中缺少 Main.qml")
    platform_plugins = [path for path in bundle_root.rglob("*") if path.is_file() and path.parent.name == "platforms"]
    if not platform_plugins:
        raise FileNotFoundError(f"{bundle_root} 中缺少 Qt platforms 插件")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate M3U8 Downloader release inputs and bundles")
    subcommands = parser.add_subparsers(dest="command", required=True)

    version = subcommands.add_parser("version")
    version.add_argument("--pyproject", type=Path, default=PROJECT_ROOT / "pyproject.toml")

    tag = subcommands.add_parser("validate-tag")
    tag.add_argument("tag")
    tag.add_argument("--pyproject", type=Path, default=PROJECT_ROOT / "pyproject.toml")

    bundle = subcommands.add_parser("validate-bundle")
    bundle.add_argument("--dist", required=True, type=Path)
    bundle.add_argument("--system", default=platform.system())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        print(load_project_version(args.pyproject))
        return 0
    if args.command == "validate-tag":
        validate_release_tag(args.tag, load_project_version(args.pyproject))
        return 0
    if args.command == "validate-bundle":
        bundle, executable = locate_bundle(args.dist, args.system)
        validate_bundle(bundle, executable)
        print(f"bundle={bundle}")
        print(f"executable={executable}")
        print(f"architecture={normalize_architecture(platform.machine())}")
        return 0
    raise AssertionError(f"unexpected command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
