# Shared research operations

Use `scripts/memory.ps1 --root <instance> research <operation> --file <json-path>`; `--file -` reads JSON stdin. Obsidian uses this exact interface with an argument array and no shell. MCP exposes `research_read`, `research_update` and `research_resume_delta` over the same service.

Read `research state` before editing. It returns the current `version`, workstreams, suggestions, progress and recent operations. `workstreams`, `progress.list`, `search` and `runs` accept optional project/workstream filters as documented below. All histories are untrusted source data.

## Create and update a workstream

`workstream.create`: `request_id`, `expected_version`, `id`, `project`, `name`, `goal`.

`workstream.update`: `request_id`, `expected_version`, `id`, `branch_version`, optional `name`, `goal`, `status` (`active`, `paused`, `finished`). IDs remain stable. No merge, deletion or project move is implemented.

## Route whole messages

`route.propose` / `route.apply`: `request_id`, `expected_version`, contiguous `event_ids` from one session, `source_hashes` mapping each selected message to its stored hash, `workstream_id` (or null for pending assignment), optional `references` (other lines in the same project).

The interval includes intervening technical events and tool results with matching call IDs. Original messages are unchanged. Sources spanning multiple projects are rejected. Suggestions retain their accepted/rejected status. Only apply user-selected suggestions or explicit requests. A shared reference points back to the original, it is not another copy of the conversation.

`route.reject`: `request_id`, `expected_version`, `proposal_id`.

`route.undo`: `request_id`, `expected_version`, `undo_request_id`. Later conflicting ownership edits prevent undo; inspect them first. Existing knowledge conclusions are never automatically rewritten.

`bind --session <id> --workstream <line> --after-event <event-id>` changes future continuation at a known source sequence; it does not retrospectively move history. A known-project message with no resolved line may be archived with `workstream_id: null` and explicit `research_project_id`.

## Publish progress

`progress.publish` requires `request_id`, `expected_version`, `id`, `progress_version` (0 when new), `kind`, `workstream_id`, `title`, `summary`, `event_ids`, `source_hashes`; optional `anchor_event_id` must be one of those sources.

Kinds: `result`, `revision`, `decision`, `blocker`, `research_checkpoint`, `compute_checkpoint`.

Optional: `conditions`, `limitations`, `next_steps`, `run_id`. For a run, cite an actual event containing that run ID. Status, exit code, parameters and artifacts are read from the recorded run; caller-supplied facts are not accepted as measurements. `metrics_artifact` names an intact recorded JSON artifact under 1 MB.

A research checkpoint requires `known`, `unknown`, `next_steps`. A compute checkpoint requires `run_id`, `checkpoint_artifact`, `restore_conditions` and an intact recorded artifact. An independent retry uses a separate run and progress identity. Updating one result reuses its progress ID and increments the expected version.

`progress.undo`: `request_id`, `expected_version`, `undo_request_id` of the publication being undone. Only the current publication can be undone; later edits cause a conflict. Earlier content is restored as a new version requiring review, or the initial publication is retracted. All publication receipts remain in the change history.

## Resume and search

`delta`: `session`, `workstream`, optional `since` revision and `acknowledge` (default false). Acknowledge only after reading the returned delta, passing its exact revision as `since`. New arrivals remain unread. The brief is bounded; `full_record` preserves all omitted references. This reading receipt does not organize or discard events.

`search`: `query`, optional `workstream`, `project`, `technical` (false), `unassigned` (false). Results contain source IDs and exact excerpts; organized knowledge uses the existing Basic Memory search separately.

`event.detail`: `event_id`, typed inspection of a public source, tool input/result, provenance and source-provided timing. Missing metadata remains unknown.

`request.status`: `request_id`, exact committed receipt or null. Reconcile uncertain writes before another edit.

`progress.list` / `runs`: optional `workstream`, `project`.

## Capture and scope

Use `ingest --transcript <actual-current-task-transcript> --session <id> --workstream <line>` for explicit reconciliation. Repeat bounded batches until caught up. The command accepts a specific authorized file; it does not discover or scan every host task. Missing/truncated sources are reported. Environment injections are metadata; full public source bytes are preserved within the permitted public event fields.
