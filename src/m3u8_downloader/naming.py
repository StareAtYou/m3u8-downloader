from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_MAX_TASK_NAME_LENGTH = 180


@dataclass(frozen=True)
class OutputPaths:
    task_name: str
    save_dir: Path
    final_path: Path


def sanitize_task_name(name: str) -> str:
    normalized = unicodedata.normalize("NFC", str(name)).strip()
    sanitized = _INVALID_FILENAME_CHARS.sub("_", normalized).rstrip(" .")
    sanitized = sanitized[:_MAX_TASK_NAME_LENGTH].rstrip(" .")

    if not sanitized or not sanitized.replace("_", "").strip(" ."):
        raise ValueError("任务名称不能为空或仅包含无效字符")

    if sanitized.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        sanitized = f"_{sanitized}"

    return sanitized


def build_output_paths(save_root: Path, task_name: str) -> OutputPaths:
    safe_name = sanitize_task_name(task_name)
    save_dir = Path(save_root).expanduser() / safe_name
    return OutputPaths(
        task_name=safe_name,
        save_dir=save_dir,
        final_path=save_dir / f"{safe_name}.mp4",
    )
