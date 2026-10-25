import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_SOURCE = REPOSITORY_ROOT / 'start.command'


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding='utf-8')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _copy_test_project(tmp_path: Path) -> Path:
    assert LAUNCHER_SOURCE.is_file(), 'start.command must exist at the repository root'
    project = tmp_path / 'project with spaces'
    project.mkdir()
    shutil.copy2(LAUNCHER_SOURCE, project / 'start.command')
    (project / 'pyproject.toml').write_text('[project]\nname = "launcher-test"\n', encoding='utf-8')
    return project


def _fake_python(tmp_path: Path) -> Path:
    fake_bin = tmp_path / 'fake bin'
    fake_bin.mkdir()
    python = fake_bin / 'python3'
    _make_executable(
        python,
        f'''#!{sys.executable}
import json
import os
from pathlib import Path
import shutil
import stat
import sys


def log_call():
    with Path(os.environ['CALL_LOG']).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(sys.argv[1:]) + '\\n')


def install_gui():
    project = Path(os.environ['PROJECT_DIR'])
    gui = project / '.venv' / 'bin' / 'm3u8-gui'
    gui.write_text(
        '#!{sys.executable}\\n'
        'import json, os, sys\\n'
        'from pathlib import Path\\n'
        "Path(os.environ['GUI_LOG']).write_text(json.dumps({{'args': sys.argv[1:], 'cwd': os.getcwd()}}), encoding='utf-8')\\n"
        "raise SystemExit(int(os.environ.get('GUI_EXIT', '0')))\\n",
        encoding='utf-8',
    )
    gui.chmod(gui.stat().st_mode | stat.S_IXUSR)


log_call()
args = sys.argv[1:]
if args and args[0] == '-c':
    if 'sys.version_info' in args[1]:
        version_ok = os.environ.get('FAKE_VERSION_OK', '1') == '1'
        if os.environ.get('OLD_VENV') == '1' and Path(__file__).name == 'python':
            version_ok = False
        raise SystemExit(0 if version_ok else 1)
    raise SystemExit(0 if Path(os.environ['READY_MARKER']).exists() else 1)
if args[:2] == ['-m', 'venv']:
    venv_python = Path(args[2]) / 'bin' / 'python'
    venv_python.parent.mkdir(parents=True)
    shutil.copy2(Path(__file__), venv_python)
    venv_python.chmod(venv_python.stat().st_mode | stat.S_IXUSR)
    raise SystemExit(0)
if args[:3] == ['-m', 'pip', 'install']:
    if os.environ.get('PIP_FAIL') == '1':
        raise SystemExit(42)
    Path(os.environ['READY_MARKER']).touch()
    install_gui()
    raise SystemExit(0)
raise SystemExit(2)
''',
    )
    return python


def _write_gui(project: Path) -> None:
    gui = project / '.venv' / 'bin' / 'm3u8-gui'
    gui.parent.mkdir(parents=True, exist_ok=True)
    _make_executable(
        gui,
        f'''#!{sys.executable}
import json
import os
from pathlib import Path
import sys

Path(os.environ['GUI_LOG']).write_text(
    json.dumps({{'args': sys.argv[1:], 'cwd': os.getcwd()}}), encoding='utf-8'
)
raise SystemExit(int(os.environ.get('GUI_EXIT', '0')))
''',
    )


def _launcher_environment(tmp_path: Path, project: Path, python: Path) -> dict[str, str]:
    fake_ffmpeg = tmp_path / 'fake ffmpeg'
    _make_executable(fake_ffmpeg, '#!/bin/sh\nexit 0\n')
    environment = os.environ.copy()
    environment.update(
        {
            'CALL_LOG': str(tmp_path / 'calls.jsonl'),
            'GUI_LOG': str(tmp_path / 'gui.json'),
            'M3U8_FFMPEG': str(fake_ffmpeg),
            'M3U8_PYTHON': str(python),
            'PROJECT_DIR': str(project),
            'READY_MARKER': str(tmp_path / 'ready'),
        }
    )
    return environment


def _run_launcher(project: Path, working_directory: Path, environment: dict[str, str], *arguments: str):
    return subprocess.run(
        ['/bin/bash', str(project / 'start.command'), *arguments],
        cwd=working_directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _calls(environment: dict[str, str]) -> list[list[str]]:
    call_log = Path(environment['CALL_LOG'])
    if not call_log.exists():
        return []
    return [json.loads(line) for line in call_log.read_text(encoding='utf-8').splitlines()]


def test_launcher_bootstraps_from_its_own_directory_and_forwards_arguments(tmp_path):
    project = _copy_test_project(tmp_path)
    python = _fake_python(tmp_path)
    environment = _launcher_environment(tmp_path, project, python)
    elsewhere = tmp_path / 'different working directory'
    elsewhere.mkdir()

    result = _run_launcher(project, elsewhere, environment, 'name with spaces', '--option', 'value with spaces')

    assert result.returncode == 0, result.stderr
    assert (project / '.venv' / 'bin' / 'python').is_file()
    assert _calls(environment).count(['-m', 'pip', 'install', '-e', f'{project}[gui]']) == 1
    launched = json.loads(Path(environment['GUI_LOG']).read_text(encoding='utf-8'))
    assert launched == {
        'args': ['name with spaces', '--option', 'value with spaces'],
        'cwd': str(elsewhere),
    }


def test_launcher_reuses_ready_environment_without_installing(tmp_path):
    project = _copy_test_project(tmp_path)
    python = _fake_python(tmp_path)
    environment = _launcher_environment(tmp_path, project, python)
    ready_python = project / '.venv' / 'bin' / 'python'
    ready_python.parent.mkdir(parents=True)
    shutil.copy2(python, ready_python)
    ready_python.chmod(ready_python.stat().st_mode | stat.S_IXUSR)
    Path(environment['READY_MARKER']).touch()
    _write_gui(project)
    isolated_path = tmp_path / 'isolated path'
    isolated_path.mkdir()
    (isolated_path / 'dirname').symlink_to(shutil.which('dirname'))
    environment.pop('M3U8_PYTHON')
    environment['PATH'] = str(isolated_path)

    result = _run_launcher(project, tmp_path, environment)

    assert result.returncode == 0, result.stderr
    assert not any(call[:3] == ['-m', 'pip', 'install'] for call in _calls(environment))
    assert Path(environment['GUI_LOG']).is_file()


def test_launcher_rejects_existing_virtualenv_older_than_311(tmp_path):
    project = _copy_test_project(tmp_path)
    python = _fake_python(tmp_path)
    environment = _launcher_environment(tmp_path, project, python)
    ready_python = project / '.venv' / 'bin' / 'python'
    ready_python.parent.mkdir(parents=True)
    shutil.copy2(python, ready_python)
    ready_python.chmod(ready_python.stat().st_mode | stat.S_IXUSR)
    Path(environment['READY_MARKER']).touch()
    _write_gui(project)
    environment['OLD_VENV'] = '1'

    result = _run_launcher(project, tmp_path, environment)

    assert result.returncode != 0
    assert '3.11' in result.stderr
    assert not Path(environment['GUI_LOG']).exists()


def test_launcher_rejects_python_older_than_311(tmp_path):
    project = _copy_test_project(tmp_path)
    python = _fake_python(tmp_path)
    environment = _launcher_environment(tmp_path, project, python)
    environment['FAKE_VERSION_OK'] = '0'

    result = _run_launcher(project, tmp_path, environment)

    assert result.returncode != 0
    assert '3.11' in result.stderr
    assert not (project / '.venv').exists()


def test_launcher_stops_when_dependency_install_fails(tmp_path):
    project = _copy_test_project(tmp_path)
    python = _fake_python(tmp_path)
    environment = _launcher_environment(tmp_path, project, python)
    environment['PIP_FAIL'] = '1'

    result = _run_launcher(project, tmp_path, environment)

    assert result.returncode != 0
    assert '安装' in result.stderr
    assert not Path(environment['GUI_LOG']).exists()


def test_launcher_warns_but_starts_without_ffmpeg(tmp_path):
    project = _copy_test_project(tmp_path)
    python = _fake_python(tmp_path)
    environment = _launcher_environment(tmp_path, project, python)
    ready_python = project / '.venv' / 'bin' / 'python'
    ready_python.parent.mkdir(parents=True)
    shutil.copy2(python, ready_python)
    ready_python.chmod(ready_python.stat().st_mode | stat.S_IXUSR)
    Path(environment['READY_MARKER']).touch()
    _write_gui(project)
    environment['M3U8_FFMPEG'] = str(tmp_path / 'missing ffmpeg')
    environment['GUI_EXIT'] = '17'

    result = _run_launcher(project, tmp_path, environment)

    assert result.returncode == 17
    assert 'FFmpeg' in result.stderr
    assert '警告' in result.stderr
    assert Path(environment['GUI_LOG']).is_file()
