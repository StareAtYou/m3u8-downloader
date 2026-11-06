# Automatic Retry, Composer Settings, and ETA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent three-attempt automatic retries, centralize desktop task defaults in Settings, align the task-name input initialization with the URL input, and display a real segment-rate ETA.

**Architecture:** SQLite v2 stores retry metadata and ETA, while `TaskManager` uses an injected UTC clock and the existing service monitor loop to promote due retries without timer threads. The worker emits segment-rate ETA values. Desktop settings own save directory and overwrite policy; the bridge injects them into single and batch submissions, and the presentation model formats ETA and pending-retry state for QML.

**Tech Stack:** Python 3.11+, SQLite, multiprocessing, PySide6/QML, pytest/pytest-qt, Ruff

**Spec:** `docs/superpowers/specs/2026-11-06-auto-retry-composer-settings-eta-design.md`

## Global Constraints

- A task may run at most four times per retry cycle: the initial attempt plus exactly three automatic retries.
- Automatic retry delays are exactly 2, 5, and 10 seconds and persist across service restarts.
- `FileExistsError`, cancellation, pause, and interruption never schedule an automatic retry.
- Manual retry resets `auto_retry_count` to zero and cancels any pending automatic retry.
- Existing CLI `save_root` and `overwrite` payloads remain compatible and explicit.
- The desktop’s existing one-task overwrite-confirmation dialog remains available without changing global settings.
- “全部开始” resumes paused tasks only and does not bypass retry backoff.
- ETA is a download wall-clock estimate based on segment completion rate, not media playback duration.

## Review Focus

- A v1 database with real tasks must migrate to v2 without losing rows, URLs, state, or output reservations; Task 1 adds a migration fixture test.
- Old JSON settings without `overwrite_existing` must load as `false`, while non-boolean values must fail; Task 1 adds both tests.
- A retry deadline that passes while the service is stopped must launch once after restart, never reset the counter or double-launch; Task 2 adds a restart test.
- Multiple retries becoming due together must re-enter the existing oldest-first scheduler without exceeding the active-task limit; Task 2 adds a FIFO/limit test.
- NaN, infinity, negative, stale, and non-downloading ETA values must never reach QML as misleading text; Tasks 1 and 5 add validation/formatting tests.

---

### Task 1: Persist retry metadata, ETA, and overwrite settings

**Files:**
- Modify: `src/m3u8_downloader/models.py`
- Modify: `src/m3u8_downloader/storage.py`
- Modify: `src/m3u8_downloader/settings_store.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_storage.py`
- Modify: `tests/test_settings_store.py`
- Modify: `tests/integration/test_service_restart.py`

**Interfaces:**
- Produces: `AppSettings.overwrite_existing: bool`
- Produces: `TaskRecord` and `TaskSnapshot` fields `auto_retry_count: int`, `next_retry_at: str | None`, and `eta_seconds: float | None`
- Produces: `TaskRepository.schedule_retry(task_id: str, next_retry_at: str) -> TaskRecord`
- Produces: `TaskRepository.list_due_retries(now: str) -> list[TaskRecord]`
- Produces: `TaskRepository.activate_scheduled_retry(task_id: str) -> TaskRecord`
- Produces: `TaskRepository.clear_retry_schedule(task_id: str, *, reset_count: bool = False) -> TaskRecord`
- Consumes: existing `TaskState.FAILED -> TaskState.QUEUED` legal transition

- [ ] **Step 1: Write failing model and migration tests**

Add tests proving `AppSettings(overwrite_existing=True)` round-trips, non-boolean values are rejected, snapshots serialize all three task fields, a hand-built v1 database migrates to schema version 2 without changing its existing task, and a fresh v2 record defaults to retry count 0 with null retry time and ETA.

- [ ] **Step 2: Run the Task 1 RED tests**

Run: `.venv/bin/python -m pytest -q tests/test_models.py tests/test_storage.py tests/test_settings_store.py tests/integration/test_service_restart.py -k "overwrite or migrate or retry_metadata or eta"`

Expected: FAIL because the settings/task fields and v2 schema do not exist.

- [ ] **Step 3: Add the v2 schema and public data fields**

Implement sequential v0/v1 → v2 migration in `TaskRepository._migrate()`. Fresh databases must be created directly at v2; v1 databases use `ALTER TABLE` for `auto_retry_count INTEGER NOT NULL DEFAULT 0`, `next_retry_at TEXT`, and `eta_seconds REAL`. Extend record creation/loading, snapshots, and `apply_worker_event()` so only finite non-negative ETA values are persisted; invalid ETA values become null.

- [ ] **Step 4: Add repository retry operations**

Implement the four produced methods. `schedule_retry` increments the counter atomically and stores the deadline while the task remains failed. `list_due_retries` returns failed tasks with non-null deadlines at or before `now`, ordered by original `created_at, task_id`. `activate_scheduled_retry` transitions to queued and clears deadline/error/ETA without changing the count. `clear_retry_schedule(reset_count=True)` also resets the count.

- [ ] **Step 5: Make overwrite settings backward compatible**

Add the strict boolean field to `AppSettings.validate()`. In `JsonSettingsStore._read_locked()`, merge the decoded mapping over `asdict(AppSettings())` before constructing `AppSettings`, so an old JSON file gains `overwrite_existing=false` while unknown keys remain errors.

- [ ] **Step 6: Run Task 1 tests and full related modules**

Run: `.venv/bin/python -m pytest -q tests/test_models.py tests/test_storage.py tests/test_settings_store.py tests/integration/test_service_restart.py`

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/m3u8_downloader/models.py src/m3u8_downloader/storage.py src/m3u8_downloader/settings_store.py tests/test_models.py tests/test_storage.py tests/test_settings_store.py tests/integration/test_service_restart.py
git commit -m "feat: persist retry metadata and eta"
```

### Task 2: Schedule three persistent automatic retries

**Files:**
- Modify: `src/m3u8_downloader/manager.py`
- Modify: `tests/test_manager.py`
- Modify: `tests/integration/test_service_restart.py`

**Interfaces:**
- Consumes: Task 1 repository retry operations and snapshot fields
- Produces: `TaskManager(..., clock: Callable[[], datetime] | None = None)` for deterministic UTC deadlines
- Produces: automatic retry delays `(2, 5, 10)` and promotion through `drain_worker_events()`
- Preserves: `resume_all()` operates only on `PAUSED`

- [ ] **Step 1: Write failing retry-cycle tests**

Add manager tests using a controllable UTC clock and existing fake launcher. Assert failure one schedules count 1 at +2 seconds without launching early; advancing the clock launches retry one; later failures use +5 and +10; the fourth failure stays final with no deadline; a `FileExistsError` event never schedules; and manual `retry()` resets count/deadline.

- [ ] **Step 2: Write failing restart and FIFO tests**

Persist a pending retry, close/reopen repository and manager with the clock past deadline, then assert exactly one launch with the existing count. Create two due retries with `max_active_tasks=1` and assert only the older task launches first. Assert `resume_all()` leaves not-yet-due failed retries untouched.

- [ ] **Step 3: Run Task 2 RED tests**

Run: `.venv/bin/python -m pytest -q tests/test_manager.py tests/integration/test_service_restart.py -k "automatic_retry or retry_deadline or due_retries or resume_all_keeps_retry"`

Expected: FAIL because the manager does not schedule or promote automatic retries.

- [ ] **Step 4: Implement deadline scheduling and promotion**

Inject the UTC clock, define `AUTO_RETRY_DELAYS = (2, 5, 10)`, and centralize task failure handling so worker `FAILED`, process launch failure, and unexpected process exit schedule a retry unless the public `error_type` is `FileExistsError` or the quota is exhausted. At the start of each `drain_worker_events()`, promote due tasks that are not in `_running`; count promotions as changes so the service broadcasts them. Reuse `_schedule_locked()` for FIFO and limits.

- [ ] **Step 5: Reset retry state on manual actions**

Make `retry()` call `clear_retry_schedule(reset_count=True)` before queuing. Ensure deletion naturally removes retry metadata with the row, and pause/resume/bulk resume do not inspect failed retry-wait tasks.

- [ ] **Step 6: Run Task 2 tests and complete manager/service coverage**

Run: `.venv/bin/python -m pytest -q tests/test_manager.py tests/test_service.py tests/integration/test_service_restart.py`

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/m3u8_downloader/manager.py tests/test_manager.py tests/integration/test_service_restart.py
git commit -m "feat: automatically retry failed downloads"
```

### Task 3: Emit segment-rate ETA from the worker

**Files:**
- Modify: `src/m3u8_downloader/worker.py`
- Modify: `tests/test_worker.py`

**Interfaces:**
- Produces: downloading `WorkerEvent.payload["eta_seconds"]: float` after at least one completed segment
- Consumes: Task 1 `TaskRepository.apply_worker_event()` ETA persistence

- [ ] **Step 1: Write the failing ETA event test**

Use a parsed playlist with four segments and a monkeypatched monotonic clock. Assert the initial downloading event has no ETA; progress events contain decreasing non-negative estimates derived from `elapsed / completed * remaining`; and the last segment reports 0.

- [ ] **Step 2: Run the Task 3 RED test**

Run: `.venv/bin/python -m pytest -q tests/test_worker.py -k eta`

Expected: FAIL because worker progress events omit `eta_seconds`.

- [ ] **Step 3: Add ETA calculation**

In the existing progress callback, compute ETA from monotonic elapsed time and completed segment count, include it beside speed, and never derive it before a segment completes. Do not change merge or completion semantics.

- [ ] **Step 4: Run all worker tests**

Run: `.venv/bin/python -m pytest -q tests/test_worker.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/m3u8_downloader/worker.py tests/test_worker.py
git commit -m "feat: report download eta from segment progress"
```

### Task 4: Move desktop task defaults into Settings

**Files:**
- Modify: `src/m3u8_downloader/gui/bridge.py`
- Modify: `src/m3u8_downloader/gui/qml/Main.qml`
- Modify: `src/m3u8_downloader/gui/qml/dialogs/BatchDialog.qml`
- Modify: `src/m3u8_downloader/gui/qml/pages/SettingsPage.qml`
- Modify: `tests/gui/test_bridge.py`
- Modify: `tests/gui/test_qml.py`

**Interfaces:**
- Produces: bridge property `overwriteExisting: bool`
- Produces: slots `submitTask(url: str, task_name: str)`, `submitTaskWithOverwrite(url: str, task_name: str)`, and `submitBatch(tasks: list[Any]) -> bool`
- Consumes: Task 1 `AppSettings.overwrite_existing`
- Preserves: service payload keys `save_root` and `overwrite`

- [ ] **Step 1: Write failing bridge tests**

Load settings with `/videos` and `overwrite_existing=true`; assert `submitTask(url, name)` and `submitBatch(tasks)` inject those exact values. Assert `submitTaskWithOverwrite` forces only the current task to true even when the global setting is false. Assert saving/loading settings emits `overwriteExistingChanged` as needed.

- [ ] **Step 2: Write failing QML contract and visual tests**

Assert task name starts empty with a non-empty placeholder matching the URL field pattern; `saveToLabel`, `saveInput`, `overwriteCheck`, and `FolderDialog` are absent; the wide and compact composer remains within bounds; Settings has `overwriteExistingCheck`; single and batch add use bridge-owned settings; and the existing conflict dialog calls `submitTaskWithOverwrite`.

- [ ] **Step 3: Run Task 4 RED tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/gui/test_bridge.py tests/gui/test_qml.py -k "submit or composer or settings or overwrite or initialization"`

Expected: FAIL because QML and bridge still take per-form save/overwrite inputs.

- [ ] **Step 4: Update the bridge settings/submission API**

Track the overwrite property beside default directory. Apply both on `get_settings` and `update_settings`. Add a shared private submission builder, expose the three produced slots, and keep protocol payloads unchanged. Batch validation remains all-or-nothing.

- [ ] **Step 5: Simplify the composer and preserve one-off overwrite**

Remove save controls and folder dialog from `Main.qml`, initialize task name with empty `text` and example `placeholderText`, reflow URL/name/buttons/preview in both layout widths, and update pending conflict data to URL/name only. Bind the conflict confirmation to `submitTaskWithOverwrite`. Remove `saveRoot`/`overwrite` properties from `BatchDialog` and call the new batch slot.

- [ ] **Step 6: Add the persistent overwrite setting**

Place `overwriteExistingCheck` below the default directory in Settings, include it in keyboard navigation and `saveSettings`, and restore it from `settingsLoaded`.

- [ ] **Step 7: Run all GUI bridge/QML tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/gui/test_bridge.py tests/gui/test_qml.py`

Expected: PASS without QML warnings.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/m3u8_downloader/gui/bridge.py src/m3u8_downloader/gui/qml/Main.qml src/m3u8_downloader/gui/qml/dialogs/BatchDialog.qml src/m3u8_downloader/gui/qml/pages/SettingsPage.qml tests/gui/test_bridge.py tests/gui/test_qml.py
git commit -m "feat: centralize desktop task defaults in settings"
```

### Task 5: Present ETA and pending retry state

**Files:**
- Modify: `src/m3u8_downloader/gui/task_list_model.py`
- Modify: `src/m3u8_downloader/gui/qml/pages/DownloadsPage.qml`
- Modify: `tests/gui/qml_harness.py`
- Modify: `tests/gui/test_task_list_model.py`
- Modify: `tests/gui/test_qml.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1 public `eta_seconds`, `auto_retry_count`, and `next_retry_at`
- Produces: presentation role `etaText: str`
- Produces: dynamic `stateLabel` value `等待重试 N/3` when a failed snapshot has a retry deadline

- [ ] **Step 1: Write failing presentation-model tests**

Add safe snapshot fields and assert ETA formats exactly as `约 45 秒`, `约 3 分钟`, `约 2 小时`, and `约 2 小时 5 分钟`. Assert invalid/negative/non-finite values and every non-downloading state render `—`. Assert a failed task with `next_retry_at` renders `等待重试 2/3`, while an exhausted failure keeps the normal failed label.

- [ ] **Step 2: Write the failing QML row test**

Populate the first downloading harness task with a positive ETA and assert `firstEta` displays the model string instead of `—`; verify a queued row remains `—` and the retry-wait badge shows its dynamic label.

- [ ] **Step 3: Run Task 5 RED tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/gui/test_task_list_model.py tests/gui/test_qml.py -k "eta or retry_wait"`

Expected: FAIL because the role and QML binding do not exist.

- [ ] **Step 4: Add safe formatting and QML binding**

Extend `TaskRole`, `ROLE_NAMES`, and `_SAFE_FIELDS`. Implement a pure `_eta_text(state: str, value: object) -> str` that rejects booleans, non-numbers, NaN, infinity, negatives, and non-downloading states. Compute pending-retry state labels from safe fields. Add `required property string etaText` to the delegate and bind the existing ETA column to it.

- [ ] **Step 5: Update documentation**

Document initial + 3 automatic retries with persistent backoff, Settings-owned save/overwrite defaults, one-off overwrite confirmation, and ETA semantics. Update the desktop usage description so it no longer instructs users to enter a save directory in the composer.

- [ ] **Step 6: Run complete GUI and documentation-adjacent tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/gui tests/test_cli.py tests/test_service.py`

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/m3u8_downloader/gui/task_list_model.py src/m3u8_downloader/gui/qml/pages/DownloadsPage.qml tests/gui/qml_harness.py tests/gui/test_task_list_model.py tests/gui/test_qml.py README.md
git commit -m "feat: display download eta and retry status"
```

### Task 6: Whole-feature verification

**Files:**
- Modify only if verification exposes a defect in the approved design

**Interfaces:**
- Consumes: all Tasks 1–5
- Produces: a fully verified branch ready for review and integration

- [ ] **Step 1: Run the complete test suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run static and formatting checks**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`

Expected: both commands pass.

- [ ] **Step 3: Inspect the final diff and worktree**

Run: `git diff --check && git status --short && git log --oneline --decorate -10`

Expected: no whitespace errors and no uncommitted product/test changes.
