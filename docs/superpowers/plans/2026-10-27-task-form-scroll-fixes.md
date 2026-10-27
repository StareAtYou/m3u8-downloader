# Task Form and Scroll Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear the task-name field after a successful single-task submission and keep the download list at the user's scroll position while active tasks refresh.

**Architecture:** Keep submission cleanup in the existing QML success callback. Change `TaskListModel.replace()` to emit row data updates when task identity and order are stable, reserving model reset for structural changes; refresh the selected-task snapshot from `dataChanged` without manipulating the `ListView` position.

**Tech Stack:** Python 3.11+, PySide6 `QAbstractListModel`, QML `ListView`, pytest, pytest-qt, Ruff

**Spec:** `docs/superpowers/specs/2026-10-27-task-form-scroll-fixes-design.md`

## Global Constraints

- A successful single-task submission clears the URL, task name, and overwrite checkbox while preserving the save directory.
- Failed submissions and overwrite confirmation keep the user's inputs intact.
- Progress-only updates preserve `ListView.contentY` and `currentIndex` while updating visible row and detail data.
- Structural changes may reset the model; task order and existing public model roles remain unchanged.
- Do not change batch submission, task ordering, or task detail layout.

## Review Focus

- A submit failure must not clear either text input; Task 1 adds a failure-path assertion.
- An overwrite-conflict response must retain the pending task and form contents; Task 1 exercises the failure signal without accepting overwrite.
- An identical snapshot must not emit refresh signals or disturb the list; Task 2 adds a no-op assertion.
- A same-length snapshot with different task IDs is still structural and must reset; Task 2 pins this case.
- Selected-task details must refresh after an incremental row update without changing selection or scroll; Task 2 covers the QML integration.

---

### Task 1: Clear task name only after successful submission

**Files:**
- Modify: `src/m3u8_downloader/gui/qml/Main.qml`
- Test: `tests/gui/test_qml.py`

**Interfaces:**
- Consumes: `AppBridge.requestSucceeded(str, object)` and `AppBridge.requestFailed(str, str)`
- Produces: successful `submit` UI cleanup for `urlInput`, `taskNameInput`, and `overwriteCheck`; `saveInput` remains unchanged

- [ ] **Step 1: Write the failing QML behavior test**

Add `test_single_submit_success_clears_transient_fields_and_failure_preserves_them`. Set literal URL, task name, save directory, and overwrite state; emit `requestFailed("submit", "网络错误")` and assert all inputs remain; then emit `requestSucceeded("submit", {"tasks": []})` and assert URL/name are empty, overwrite is false, and save directory is unchanged.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/gui/test_qml.py::test_single_submit_success_clears_transient_fields_and_failure_preserves_them -q`

Expected: FAIL because `taskNameInput.text` still contains the submitted name after success.

- [ ] **Step 3: Implement the minimal success cleanup**

In `Main.qml`'s `onRequestSucceeded`, add `taskNameInput.text = ""` inside the existing `action === "submit"` branch. Do not clear it before success or in the failure handler.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/gui/test_qml.py::test_single_submit_success_clears_transient_fields_and_failure_preserves_them -q`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/m3u8_downloader/gui/qml/Main.qml tests/gui/test_qml.py
git commit -m "fix: clear task name after successful submission"
```

### Task 2: Incrementally refresh stable task rows without resetting scroll

**Files:**
- Modify: `src/m3u8_downloader/gui/task_list_model.py`
- Modify: `src/m3u8_downloader/gui/qml/pages/DownloadsPage.qml`
- Test: `tests/gui/test_task_list_model.py`
- Test: `tests/gui/test_qml.py`

**Interfaces:**
- Consumes: `TaskListModel.replace(snapshots: list[dict[str, Any]]) -> None` and Qt's inherited `dataChanged(QModelIndex, QModelIndex, list[int])`
- Produces: reset-free row updates when the ordered `task_id` sequence is unchanged; structural updates retain reset semantics; selected-task details refresh on `dataChanged`

- [ ] **Step 1: Write failing model signal tests**

Add tests asserting that:

- changing progress/state for stable ordered task IDs emits `dataChanged` over only the changed row and emits neither `modelReset` nor `countChanged`;
- replacing a snapshot with identical safe data emits none of those signals;
- changing the ordered task-ID sequence emits `modelReset` and `countChanged`.

- [ ] **Step 2: Run model tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/gui/test_task_list_model.py -q`

Expected: FAIL because every `replace()` currently emits `modelReset` and `countChanged` and never emits `dataChanged`.

- [ ] **Step 3: Implement stable-identity incremental updates**

In `TaskListModel.replace()`:

- sanitize snapshots exactly as today;
- compare the old and new ordered `task_id` lists;
- use `beginResetModel()/endResetModel()` plus `countChanged` only when those lists differ;
- otherwise update `_items` and emit inherited `dataChanged` for each contiguous range of rows whose safe dictionaries changed, passing all presentation role integers.

- [ ] **Step 4: Run model tests and verify GREEN**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/gui/test_task_list_model.py -q`

Expected: all model tests PASS.

- [ ] **Step 5: Write the failing QML scroll-and-detail integration test**

Add `test_active_task_refresh_preserves_task_list_scroll_and_selection`. Load `many_tasks()`, select a literal nonzero index, set `taskTable.contentY` to a literal in-range offset, update the selected downloading task without changing task IDs/order, call `bridge.tasks.replace(updated)`, and assert:

- `contentY` remains within one pixel of the saved offset;
- `currentIndex` is unchanged;
- the selected detail progress/segment value reflects the updated snapshot.

- [ ] **Step 6: Run the QML test and verify RED**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/gui/test_qml.py::test_active_task_refresh_preserves_task_list_scroll_and_selection -q`

Expected: FAIL before the model change due to scroll reset, or after the model change because the selected-task snapshot is not yet refreshed by `dataChanged`.

- [ ] **Step 7: Refresh selected details from incremental model changes**

In the existing `Connections { target: page.taskModel }` block in `DownloadsPage.qml`, add `onDataChanged` that schedules `page.refreshSelectedTask()` with `Qt.callLater`. Do not assign `contentY` or call a positioning method.

- [ ] **Step 8: Run focused GUI tests and verify GREEN**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/gui/test_task_list_model.py tests/gui/test_qml.py -q`

Expected: all focused tests PASS with no QML warnings.

- [ ] **Step 9: Run complete verification**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`

Run: `.venv/bin/ruff check src tests scripts server.py client.py`

Run: `.venv/bin/ruff format --check src tests scripts server.py client.py`

Expected: all commands exit 0.

- [ ] **Step 10: Commit Task 2**

```bash
git add src/m3u8_downloader/gui/task_list_model.py src/m3u8_downloader/gui/qml/pages/DownloadsPage.qml tests/gui/test_task_list_model.py tests/gui/test_qml.py
git commit -m "fix: preserve task list position during progress updates"
```
