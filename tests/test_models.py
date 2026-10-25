from dataclasses import replace

import pytest

from m3u8_downloader.models import (
    LEGAL_TRANSITIONS,
    AppSettings,
    OverwritePolicy,
    TaskRecord,
    TaskState,
    validate_transition,
)


def test_manual_proxy_policy_requires_a_local_proxy_url() -> None:
    with pytest.raises(ValueError, match="手动代理"):
        AppSettings(proxy_policy="manual").validate()


def make_task() -> TaskRecord:
    return TaskRecord.new(
        task_id="task-1",
        url="https://media.example/video.m3u8?token=secret&expires=123",
        task_name="演示",
        filename="演示.mp4",
        save_root="/tmp/videos",
        workspace="/tmp/work/task-1",
        final_path="/tmp/videos/演示/演示.mp4",
        overwrite_policy=OverwritePolicy.REJECT,
    )


def test_validates_complete_legal_transition_table() -> None:
    for current in TaskState:
        for target in TaskState:
            if target in LEGAL_TRANSITIONS[current]:
                validate_transition(current, target)
            elif target != current:
                with pytest.raises(ValueError):
                    validate_transition(current, target)


def test_rejects_completed_restart_and_merging_pause() -> None:
    with pytest.raises(ValueError):
        validate_transition(TaskState.COMPLETED, TaskState.DOWNLOADING)
    with pytest.raises(ValueError):
        validate_transition(TaskState.MERGING, TaskState.PAUSED)


def test_public_snapshot_redacts_signed_url() -> None:
    task = replace(make_task(), state=TaskState.DOWNLOADING, completed=2, total=10)

    snapshot = task.to_snapshot()

    assert task.url.endswith("token=secret&expires=123")
    assert snapshot.redacted_url == "https://media.example/video.m3u8?token=%2A%2A%2A&expires=%2A%2A%2A"
    assert "secret" not in snapshot.to_dict().values()


def test_public_snapshot_strips_credentials_and_fragment() -> None:
    record = replace(make_task(), url="https://alice:secret@media.example/video.m3u8?token=x#private")

    assert record.to_snapshot().redacted_url == "https://media.example/video.m3u8?token=%2A%2A%2A"


def test_event_payload_cannot_include_private_url() -> None:
    event = make_task().event(TaskState.PROBING, {"route": "直连"})

    assert event.to_dict() == {
        "task_id": "task-1",
        "state": "probing",
        "payload": {"route": "直连"},
    }


def test_rejects_sensitive_event_payload() -> None:
    with pytest.raises(ValueError, match="敏感"):
        make_task().event(TaskState.PROBING, {"url": "https://example.test/?token=secret"})
