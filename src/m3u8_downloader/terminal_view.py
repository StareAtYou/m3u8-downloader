from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from rich.console import Console
from rich.table import Table

STATE_LABELS = {
    "queued": "排队中",
    "probing": "线路测速",
    "parsing": "解析中",
    "downloading": "下载中",
    "paused": "已暂停",
    "waiting_merge": "等待合并",
    "merging": "合并中",
    "completed": "已完成",
    "canceling": "取消中",
    "canceled": "已取消",
    "failed": "失败",
    "interrupted": "已中断",
}


def render_tasks(console: Console, tasks: Sequence[Mapping[str, Any]]) -> None:
    table = Table(title="M3U8 下载任务", expand=True)
    table.add_column("任务", no_wrap=True)
    table.add_column("状态", no_wrap=True)
    table.add_column("进度", justify="right", no_wrap=True)
    table.add_column("通道")
    table.add_column("信息")
    for task in tasks:
        completed = int(task.get("completed", 0) or 0)
        total = int(task.get("total", 0) or 0)
        progress = f"{completed}/{total}" if total else "—"
        table.add_row(
            str(task.get("task_name") or task.get("task_id", "")),
            STATE_LABELS.get(str(task.get("state", "")), str(task.get("state", ""))),
            progress,
            str(task.get("route") or "—"),
            str(task.get("error") or ""),
        )
    console.print(table)
