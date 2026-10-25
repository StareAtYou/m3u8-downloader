from pathlib import Path

import pytest

from m3u8_downloader.naming import build_output_paths, sanitize_task_name


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("  风起长安: 第01集?  ", "风起长安_ 第01集_"),
        ("片名. ", "片名"),
        ("CON", "_CON"),
        ("a/b\\c|d*e\"f<g>h", "a_b_c_d_e_f_g_h"),
    ],
)
def test_sanitizes_cross_platform_invalid_characters(raw_name: str, expected: str) -> None:
    assert sanitize_task_name(raw_name) == expected


@pytest.mark.parametrize("raw_name", ["", "   ", "...", "\x00\x01"])
def test_rejects_empty_sanitized_name(raw_name: str) -> None:
    with pytest.raises(ValueError, match="任务名称"):
        sanitize_task_name(raw_name)


def test_builds_task_named_mp4_path(tmp_path: Path) -> None:
    output = build_output_paths(tmp_path, "演示视频")

    assert output.task_name == "演示视频"
    assert output.save_dir == tmp_path / "演示视频"
    assert output.final_path == tmp_path / "演示视频" / "演示视频.mp4"
