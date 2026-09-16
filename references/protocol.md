# JSON contracts

Output paths are beneath the private data root. Inputs may also belong to the installation or an explicitly registered workspace; transcripts must be explicitly selected. Commands take a JSON file, avoiding shell interpolation of prompts or code. Stable IDs contain ASCII letters, digits, `_`, `-`.

For the partitioned vault, set `research_project_id` on new events, runs, notes and extraction batches (for example `research-memory-personal`). It must match the branch binding; this is distinct from the immutable archive `project_id`. See `projects.md`. A public AI research observation is a message with `author: "assistant"` and a payload containing `text`, `observation`, `candidate_explanation`, `conditions`, `source_event_ids`, `alternatives`, and `verification_plan`; fields outside `text` remain in the canonical envelope. Record only statements the current model explicitly publishes, never hidden reasoning. Candidate notes cite these public events and remain unreviewed/unassessed until separate review/evidence updates.

Event:
```json
{"source":"manual-public-message","source_id":"task-id:message-1","session_id":"task-id","workstream_id":"system-development","kind":"message","author":"user","payload":{"text":"Complete public prompt"},"occurred_at":"2026-09-08T12:00:00Z","source_sequence":1,"predecessors":[],"completeness":"public_message"}
```

Extraction batch:
```json
{"processor":"active-codex/research-memory-v1","event_ids":["ev_..."],"notes":[{"id":"idea-example","type":"idea","title":"Candidate explanation","workstream_id":"system-development","authors":["user"],"conditions":["Only for the measured sample"],"sources":[{"event_id":"ev_...","quote":"Exact source excerpt"}],"body":"Candidate interpretation and testable prediction.","human_review":"unreviewed","evidence_status":"unassessed","relations":[],"expected_version":0}]}
```

No-candidate batch has `notes: []` and a nonempty `no_candidate_reason`. Version checks apply to individual notes and checkpoints. Links in `relations` use `{type,target,basis}`; supports, contradicts, adopts and rejects also require a nonempty basis and `source_event_ids` referring to actual archived evidence or decision records. Allowed types: derived_from, extends, depends_on, supports, contradicts, refines, replaces, related_to, tests, adopts, rejects. Adoption/rejection relations originate from a decision note; they never imply scientific validation. `related_to` is symmetric. Read each directed relation as source — predicate → target.

Canonical `id` and relation `target` remain stable ASCII IDs. Human-facing filenames are resolved from `data/view-paths.json`; Markdown uses `[[current path|readable title]]`. Sources have independent immutable event files and rebuildable Markdown reading pages. Physical paths must not be inferred from an ID.

Evidence notes also contain `evidence` with `url`, `locator`, `excerpt`, `access_level` (full_text, abstract_only, metadata_only, local_artifact), `verification` (unverified or verified), optional bibliographic fields, and `checked_source_event` for verified records. A verified source retrieval does not itself prove a hypothesis.

Run:
```json
{"request_id":"unique-exp-001","workstream_id":"system-development","session_id":"task-id","purpose":"Test a defined prediction","argv":["D:/absolute/python.exe","D:/project/examples/experiment.py"],"inputs":["examples/experiment.py"],"parameters":{"seed":42},"resources":["dataset:sample-a"],"code_root":"."}
```

The child receives `RESEARCH_RUN_ID`, `RESEARCH_RUN_DIR`, `RESEARCH_ARTIFACT_DIR`. Its working directory is its run directory. Full stdout/stderr are files there. Parameters are archived; pass them explicitly via argv if the program needs them.

Checkpoint:
```json
{"workstream_id":"system-development","expected_version":0,"data":{"goal":"Research goal","decisions":[],"ideas":[],"evidence":[],"open_questions":[],"next_steps":[],"dependencies":["examples/experiment.py"]}}
```
