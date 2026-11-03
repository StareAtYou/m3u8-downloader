# Task Controls, Deletion, and Settings Persistence Design

## Intent

Make the desktop task list behave like an operational download queue: new submissions appear first, all resumable work can be paused or resumed in one click, obsolete tasks can be removed safely, and saved settings survive a complete GUI and service restart in an explicit local configuration file.

## Goals

- Show the newest task at the top of the GUI and terminal task list without changing FIFO download scheduling.
- Add visible “全部开始” and “全部暂停” controls for all unfinished tasks.
- Allow deleting one task record, or deleting the record plus files owned by that task.
- Persist the complete `AppSettings` value in an atomic local JSON file and migrate the existing SQLite-backed value on first use.
- Keep task updates, deletion, and settings changes owned by the background service so GUI and CLI clients observe the same state.

## Non-goals and safety boundaries

- “全部开始” resumes paused tasks only. It does not silently retry failed, canceled, or interrupted tasks.
- “全部暂停” pauses queued/downloading work. A task already merging is allowed to finish because the merge is atomic and is not safely pausable.
- Record-only deletion never deletes output or workspace files.
- Record-and-files deletion removes the task workspace in every state, but removes the final output only when the task reached `completed`; this avoids deleting a pre-existing file belonging to the user after an incomplete overwrite attempt.
- The service never deletes a parent save directory or any path inferred from the task name; it deletes only the exact stored workspace and eligible exact final output path.

## Chosen approach

The service exposes `resume_all` and `delete_task` protocol actions. `TaskManager` coordinates state transitions and file ownership. Deletion is available only when no worker owns the task: paused, interrupted, failed, canceled, and completed tasks may be deleted, along with queued tasks that have not been dispatched. Probing, parsing, downloading, waiting-to-merge, merging, and canceling tasks must first reach a safe paused or terminal state. This makes “仅删除记录” literal: it never cancels a worker that would independently remove its workspace, and it avoids invisible background work after a record disappears.

Task listing becomes newest-first, while `_schedule_locked()` explicitly requests oldest-first snapshots so the established FIFO queue remains unchanged. The GUI adds bulk controls above the task table and a delete action per row. Deletion opens one confirmation dialog with two explicit choices: “仅删除记录” and “删除记录和本地文件”.

Settings move to `settings.json` under the platform configuration directory. A focused settings store validates values, writes through a same-directory temporary file followed by `os.replace`, and uses private permissions where supported. When the file does not exist, it reads the existing repository value once and writes it to JSON, preserving current users’ settings. `TaskManager` accepts the store through dependency injection; tests may continue using the repository-backed adapter when no file store is supplied.

## Alternatives considered

1. **Recommended and selected: service-owned operations plus JSON settings store.** This keeps every client consistent, provides safe cancellation-before-deletion, and makes settings explicit and portable. It adds a small manager/store interface but does not duplicate business rules in QML.
2. **GUI-only ordering, deletion, and QSettings.** This is smaller, but terminal clients would see different ordering, deletion could race active workers, and service download parameters could diverge from GUI settings.
3. **Keep settings only in SQLite and call it a local file.** Technically persistent already, but it does not meet the requested explicit local settings-file behavior and is harder for users to back up or inspect.

## Data and control flow

1. The repository returns public snapshots newest-first; the scheduler asks for oldest-first.
2. GUI bulk actions call the bridge, which sends `pause_all` or `resume_all` asynchronously.
3. GUI deletion passes `{task_id, delete_files}`. The manager rejects worker-owned active tasks and removes eligible records synchronously.
4. Task changes continue through the existing `tasks_changed` subscription; no GUI-local shadow state is introduced.
5. Settings requests flow through the manager to the injected settings store. Production uses JSON with repository fallback/migration.

## Error handling

- Missing task IDs return the existing request error path and do not touch files.
- Repeating deletion of a missing task reports that the record no longer exists and never touches files.
- Before deleting a completed output, the manager rejects the operation if any other task record references the same normalized final path. This prevents an older completed record from deleting a later overwrite. For a unique path, the explicit confirmation authorizes deletion of that exact stored file; external replacement cannot be proven from legacy records, so the dialog displays the exact path and warns that it will be removed.
- File deletion treats a missing exact task path as already deleted, but reports other filesystem failures and keeps the database record so the user can retry.
- Invalid or corrupt JSON does not overwrite the file silently; loading reports a validation error through the service.
- Settings are only reported as saved after the atomic replace succeeds.

## UI behavior

- A compact control strip sits directly above the table header. “全部开始” is enabled when at least one task is paused; “全部暂停” is enabled when at least one task is pausable.
- Each row keeps its current pause/resume/retry/open/cancel actions and adds a trash action.
- The delete dialog names the task, explains both scopes, and defaults to the non-destructive record-only choice.
- The trash action is disabled while a worker owns the task and explains that the task must first be paused or allowed to finish.
- After deletion, selection/detail state refreshes through the model; progress-only updates still do not reset list scroll position.

## Verification

- Repository tests prove newest-first display and oldest-first scheduling.
- Manager/service tests prove bulk resume, deletion in idle and active states, exact file ownership, and protocol dispatch.
- Settings-store tests prove atomic persistence, restart loading, legacy migration, validation, and permissions.
- Bridge/QML tests prove bulk actions, delete payloads, confirmation choices, and enabled-state behavior.
- Full pytest and Ruff checks remain green.
