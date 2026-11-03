# Task Controls, Deletion, and Settings Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add newest-first task display, safe bulk pause/resume, task deletion with two file scopes, and restart-safe JSON settings persistence.

**Architecture:** The background service remains the source of truth. Repository ordering separates display order from scheduler order, manager methods own bulk and deletion rules, and production settings are injected through an atomic JSON store with legacy SQLite fallback. QML only presents service-backed state and confirmations.

**Tech Stack:** Python 3.11+, SQLite, JSON, PySide6/QML, pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-11-03-task-controls-deletion-settings-design.md`

## Global Constraints

- Display newest tasks first while scheduling queued work oldest first.
- Bulk start resumes only paused tasks; it does not retry failed, canceled, or interrupted tasks.
- Merging tasks are never force-paused.
- Record-only deletion never deletes workspace or output files.
- Record-and-files deletion removes the exact workspace and removes the exact final output only for completed tasks with no other record referencing that normalized path.
- Worker-owned active tasks cannot be deleted.
- Settings writes are validated, atomic, private where supported, and migrate the existing repository setting on first use.

## Review Focus

- Two tasks created in the same clock tick must have deterministic newest/oldest ordering; Task 1 tests the `task_id` tie-break.
- Mixed queued/running/paused/completed states must bulk-control only eligible tasks; Task 2 tests the full state mix.
- Delete-with-files must not remove a shared output or any parent directory; Task 3 tests both cases.
- A malformed settings file must remain untouched and surface an error rather than resetting defaults; Task 4 tests this.
- Structural task changes must update bulk button state and selection without reintroducing progress-update scroll jumps; Task 5 tests model signals and QML scroll behavior.

---

### Task 1: Newest-first display with FIFO scheduling

**Files:**
- Modify: `src/m3u8_downloader/storage.py`
- Modify: `src/m3u8_downloader/manager.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_manager.py`

**Interfaces:**
- Produces: `TaskRepository.list_snapshots(*, newest_first: bool = True) -> list[TaskSnapshot]`
- Consumes: existing `TaskManager.list()` and `_schedule_locked()`

- [ ] **Step 1: Write failing repository and manager tests**

Add `test_lists_newest_first_with_deterministic_tie_break_and_oldest_on_request` and `test_newest_first_display_keeps_oldest_first_scheduler` with literal task IDs/order assertions.

- [ ] **Step 2: Verify RED**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_storage.py::test_lists_newest_first_with_deterministic_tie_break_and_oldest_on_request tests/test_manager.py::test_newest_first_display_keeps_oldest_first_scheduler -q`
Expected: FAIL because `newest_first` is unsupported and public order is oldest-first.

- [ ] **Step 3: Implement ordering separation**

Make repository public listing default to `ORDER BY created_at DESC, task_id DESC`; request ascending order in `_schedule_locked()` only.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 command; expected `2 passed`.

- [ ] **Step 5: Commit**

Commit message: `feat: show newest download tasks first`

### Task 2: Bulk pause and resume service operations

**Files:**
- Modify: `src/m3u8_downloader/manager.py`
- Modify: `src/m3u8_downloader/protocol.py`
- Modify: `src/m3u8_downloader/service.py`
- Modify: `tests/test_manager.py`
- Modify: `tests/test_protocol.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Produces: `TaskManager.resume_all() -> list[str]`
- Produces: protocol action `resume_all` returning `{ "task_ids": list[str] }`
- Consumes: existing `pause_all()` and `resume(task_id)`

- [ ] **Step 1: Write failing mixed-state manager, protocol, and dispatch tests**

Prove pause-all skips merging/terminal states, resume-all resumes paused tasks only, and the service returns affected IDs.

- [ ] **Step 2: Verify RED**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_manager.py -k 'pause_all or resume_all' tests/test_protocol.py tests/test_service.py -q`
Expected: FAIL because `resume_all` is not accepted or implemented.

- [ ] **Step 3: Implement `resume_all` and dispatch**

Iterate snapshots under the manager lock-safe public methods; do not retry terminal states.

- [ ] **Step 4: Verify GREEN**

Run the Task 2 command; expected all selected tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: add bulk pause and resume controls`

### Task 3: Safe record and file deletion

**Files:**
- Modify: `src/m3u8_downloader/storage.py`
- Modify: `src/m3u8_downloader/manager.py`
- Modify: `src/m3u8_downloader/protocol.py`
- Modify: `src/m3u8_downloader/service.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_manager.py`
- Modify: `tests/test_protocol.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Produces: `TaskRepository.delete_task(task_id: str) -> None`
- Produces: `TaskManager.delete(task_id: str, *, delete_files: bool = False) -> dict[str, object]`
- Produces: protocol action `delete_task` with `{task_id: str, delete_files: bool}`

- [ ] **Step 1: Write failing deletion tests**

Cover record-only preservation, completed file/workspace deletion, non-completed final preservation, active-worker rejection, exact missing paths, shared-output rejection, and parent-directory preservation.

- [ ] **Step 2: Verify RED**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_storage.py -k delete tests/test_manager.py -k delete tests/test_protocol.py tests/test_service.py -k 'delete or dispatch' -q`
Expected: FAIL because deletion interfaces/actions do not exist.

- [ ] **Step 3: Implement repository, manager, and service deletion**

Perform all filesystem checks and deletions before removing the record. Treat missing exact paths as success; reject worker-owned states and shared normalized final paths.

- [ ] **Step 4: Verify GREEN**

Run the Task 3 command; expected all selected tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: safely delete download tasks`

### Task 4: Atomic local settings file with migration

**Files:**
- Create: `src/m3u8_downloader/settings_store.py`
- Modify: `src/m3u8_downloader/manager.py`
- Modify: `src/m3u8_downloader/cli.py`
- Create: `tests/test_settings_store.py`
- Modify: `tests/test_manager.py`
- Modify: `tests/integration/test_service_restart.py`

**Interfaces:**
- Produces: `JsonSettingsStore(path: Path, fallback: Callable[[], AppSettings] | None = None)`
- Produces: `get_settings() -> AppSettings` and `update_settings(settings: AppSettings) -> None`
- Changes: `TaskManager(..., settings_store: object | None = None)`; `None` keeps repository compatibility for tests/embedders.

- [ ] **Step 1: Write failing persistence, migration, corruption, permission, and restart tests**

Assert literal JSON values after update, reload after a fresh store/manager, first-read fallback migration, unchanged malformed bytes on error, mode `0600` on non-Windows, and service restart preserving all fields.

- [ ] **Step 2: Verify RED**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_store.py tests/test_manager.py -k settings tests/integration/test_service_restart.py -q`
Expected: FAIL because `JsonSettingsStore` does not exist.

- [ ] **Step 3: Implement atomic JSON store and inject it in production service startup**

Serialize `asdict(AppSettings)` to a same-directory temporary file, flush/fsync, chmod where supported, and `os.replace`. Serialize access with a lock.

- [ ] **Step 4: Verify GREEN**

Run the Task 4 command; expected all selected tests pass.

- [ ] **Step 5: Commit**

Commit message: `feat: persist settings in local json file`

### Task 5: Desktop bulk controls and deletion UI

**Files:**
- Modify: `src/m3u8_downloader/gui/task_list_model.py`
- Modify: `src/m3u8_downloader/gui/bridge.py`
- Modify: `src/m3u8_downloader/gui/qml/Main.qml`
- Modify: `src/m3u8_downloader/gui/qml/pages/DownloadsPage.qml`
- Modify: `src/m3u8_downloader/gui/qml/pages/CompletedPage.qml`
- Modify: `tests/gui/test_task_list_model.py`
- Modify: `tests/gui/test_bridge.py`
- Modify: `tests/gui/test_qml.py`
- Modify: `README.md`

**Interfaces:**
- Produces: model properties `pausableCount`, `pausedCount` with change notification and role `canDelete`
- Produces: bridge slots `resumeAll()` and `deleteTask(task_id: str, delete_files: bool)`
- Produces: page signal `deleteRequested(taskId, taskName, finalPath)` handled by one Main.qml confirmation dialog

- [ ] **Step 1: Write failing model, bridge, and QML behavior tests**

Prove count notifications on state changes, exact request payloads, enabled bulk buttons, both deletion scopes, completed-page deletion, and preserved list `contentY` during progress-only updates.

- [ ] **Step 2: Verify RED**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/gui/test_task_list_model.py tests/gui/test_bridge.py tests/gui/test_qml.py -q`
Expected: FAIL because the properties, slots, buttons, and dialog do not exist.

- [ ] **Step 3: Implement the UI and update user documentation**

Add a compact bulk toolbar above the table, add trash actions to download/completed rows, centralize the safe confirmation dialog in `Main.qml`, and document `settings.json` plus deletion semantics.

- [ ] **Step 4: Verify GREEN and layout quality**

Run the Task 5 command; expected all GUI tests pass with no QML warnings.

- [ ] **Step 5: Run full verification**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all tests pass; Ruff reports no issues and no formatting changes needed.

- [ ] **Step 6: Commit**

Commit message: `feat: add desktop task management controls`
