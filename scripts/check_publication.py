from __future__ import annotations

import argparse
import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ALLOW_MARKER_PREFIX = "publication-scan: allow-"
FORBIDDEN_SUFFIXES = {
    ".avi",
    ".bundle",
    ".flv",
    ".key",
    ".m4s",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".p12",
    ".part",
    ".pem",
    ".pfx",
    ".ts",
    ".webm",
    ".wmv",
}
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
ALLOWED_EMAIL_DOMAINS = {
    "cdn.example.com",
    "github.com",
    "media.example",
    "users.noreply.github.com",
}
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (  # publication-scan: allow-rule-definition
        "10.0.0.0/8",  # publication-scan: allow-rule-definition
        "172.16.0.0/12",  # publication-scan: allow-rule-definition
        "192.168.0.0/16",  # publication-scan: allow-rule-definition
    )
)

USER_PATH_PATTERNS = (
    ("posix-user-path", re.compile(r"/(?:Users|home)/[^/\s]+")),  # publication-scan: allow-rule-definition
    ("windows-user-path", re.compile(r"[A-Za-z]:\\+Users\\+[^\\\s]+", re.IGNORECASE)),
)
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])([\w.+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,}))(?![\w.-])")
IPV4_PATTERN = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
GITHUB_TOKEN_PATTERN = re.compile(r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})")
PRINTABLE_PATTERN = re.compile(rb"[\x20-\x7e]{6,}")


@dataclass(frozen=True)
class Finding:
    path: Path
    rule: str
    line: int | None = None


def _forbidden_path(path: Path) -> bool:
    posix = path.as_posix()
    return (
        path.is_absolute()
        or ".." in path.parts
        or posix == "design-qa.md"
        or posix.startswith("docs/superpowers/")
        or path.suffix.lower() in FORBIDDEN_SUFFIXES
        or posix.endswith(".tar.gz")
    )


def _scan_text(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER_PREFIX in line:
            continue
        for rule, pattern in USER_PATH_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(path, rule, line_number))
        for match in EMAIL_PATTERN.finditer(line):
            if match.group(2).lower() not in ALLOWED_EMAIL_DOMAINS:
                findings.append(Finding(path, "email", line_number))
                break
        for match in IPV4_PATTERN.finditer(line):
            try:
                address = ipaddress.ip_address(match.group(0))
            except ValueError:
                continue
            if any(address in network for network in PRIVATE_NETWORKS):
                findings.append(Finding(path, "private-ip", line_number))
                break
        if PRIVATE_KEY_PATTERN.search(line):
            findings.append(Finding(path, "private-key", line_number))
        if GITHUB_TOKEN_PATTERN.search(line):
            findings.append(Finding(path, "github-token", line_number))
    return findings


def _read_scannable_text(path: Path) -> str | None:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            return None
        return "\n".join(match.decode("ascii") for match in PRINTABLE_PATTERN.findall(data))


def scan_paths(root: Path, relative_paths: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for relative_path in relative_paths:
        if _forbidden_path(relative_path):
            findings.append(Finding(relative_path, "forbidden-path"))
            continue
        target = root / relative_path
        if target.is_symlink():
            findings.append(Finding(relative_path, "symlink"))
            continue
        if not target.is_file():
            findings.append(Finding(relative_path, "missing-file"))
            continue
        text = _read_scannable_text(target)
        if text is not None:
            findings.extend(_scan_text(relative_path, text))
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan an explicit tracked-file manifest before publication")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--paths-from", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = [Path(raw.decode("utf-8")) for raw in args.paths_from.read_bytes().split(b"\0") if raw]
    findings = scan_paths(args.root, paths)
    for finding in findings:
        location = f":{finding.line}" if finding.line is not None else ""
        print(f"{finding.path.as_posix()}{location}: {finding.rule}")
    for path in paths:
        if path.suffix.lower() in IMAGE_SUFFIXES and not _forbidden_path(path):
            print(f"REVIEW image: {path.as_posix()}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
