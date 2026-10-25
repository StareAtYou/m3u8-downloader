#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$SCRIPT_DIR"
VENV_DIR="$PROJECT_ROOT/.venv"

python_is_compatible() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

VENV_PYTHON="$VENV_DIR/bin/python"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    PYTHON_COMMAND=""
    if [[ -n "${M3U8_PYTHON:-}" ]]; then
        if ! command -v "$M3U8_PYTHON" >/dev/null 2>&1; then
            printf '错误：找不到指定的 Python：%s\n' "$M3U8_PYTHON" >&2
            exit 1
        fi
        if ! python_is_compatible "$M3U8_PYTHON"; then
            printf '错误：M3U8 Downloader Pro 需要 Python 3.11 或更高版本。\n' >&2
            exit 1
        fi
        PYTHON_COMMAND="$M3U8_PYTHON"
    else
        for candidate in python3 python3.13 python3.12 python3.11; do
            if command -v "$candidate" >/dev/null 2>&1 && python_is_compatible "$candidate"; then
                PYTHON_COMMAND="$candidate"
                break
            fi
        done
        if [[ -z "$PYTHON_COMMAND" ]]; then
            printf '错误：未找到 Python 3.11 或更高版本。请先安装兼容的 Python 后重试。\n' >&2
            exit 1
        fi
    fi

    printf '首次启动：正在创建项目虚拟环境……\n'
    if ! "$PYTHON_COMMAND" -m venv "$VENV_DIR"; then
        printf '错误：创建虚拟环境失败。请确认 Python 的 venv 功能可用，并检查目录权限。\n' >&2
        exit 1
    fi
fi

if ! python_is_compatible "$VENV_PYTHON"; then
    printf '错误：项目 .venv 使用的 Python 低于 3.11。请删除 .venv 后重新运行本脚本。\n' >&2
    exit 1
fi

if ! "$VENV_PYTHON" -c 'import m3u8_downloader, PySide6, qtawesome' >/dev/null 2>&1; then
    printf '正在安装桌面界面依赖，首次启动可能需要几分钟……\n'
    if ! "$VENV_PYTHON" -m pip install -e "$PROJECT_ROOT[gui]"; then
        printf '错误：桌面界面依赖安装失败。请检查网络连接和上方的 pip 错误信息。\n' >&2
        exit 1
    fi
fi

FFMPEG_COMMAND="${M3U8_FFMPEG:-ffmpeg}"
if ! command -v "$FFMPEG_COMMAND" >/dev/null 2>&1; then
    printf '警告：未找到 FFmpeg。界面仍会启动；请安装 FFmpeg，或在设置中填写其绝对路径。\n' >&2
fi

GUI_COMMAND="$VENV_DIR/bin/m3u8-gui"
if [[ ! -x "$GUI_COMMAND" ]]; then
    printf '错误：未找到桌面界面启动程序。请删除项目中的 .venv 后重新运行本脚本。\n' >&2
    exit 1
fi

exec "$GUI_COMMAND" "$@"
