# Research projects and recovery

The outer `config.json.project_id` identifies the immutable event archive. `data/research-projects.json` identifies research projects and their Basic Memory index mappings. A `workstream_id` belongs to one research project; a Codex task binds to a workstream. Several tasks may continue that branch. Do not use a window or the last active task as the owner of knowledge.

From the installed skill directory, add `--root <private-instance>` after `memory.ps1`:

```powershell
./scripts/memory.ps1 projects
./scripts/memory.ps1 project-register anomaly-study --name "时序异常研究" --goal "比较异常解释与实验结果"
./scripts/memory.ps1 bind --session <actual-task-id> --project anomaly-study --workstream anomaly-main --create --goal "研究主分支"
./scripts/memory.ps1 resume --workstream anomaly-main --project anomaly-study
./scripts/memory.ps1 status --project anomaly-study
./scripts/memory.ps1 reindex --project anomaly-study
./scripts/memory.ps1 reindex --project anomaly-study --embeddings
```

Use a `research_project_id` in new events, runs and extraction batches. Branch inference is accepted only when its registry binding is unambiguous; a mismatched explicit project/session/branch is rejected. Note IDs are unique across the archive even when titles match. Historical raw events and run intents retain their bytes; `project-ownership.json` provides versioned membership and effective workstream overlays.

Each project lives under `研究项目/<name>` or `示例与验收/<name>`. Canonical knowledge has six categories. Sources use month and stable readable session labels; their exact session identity and original timestamps stay in the audit details. Different days in the same research project stay together. Raw events and full logs remain under the engineering `data`/`runs` directories.

`views` updates managed homes, Bases, run pages, incoming relationships and the graph. A user-edited note generates a pending view under `data/conflicts` instead of being overwritten. A user-edited navigation page raises a conflict; compare its text with the generated proposal/backups before merging. Current scientific statements, manual review and evidence status are never inferred from a file rename.

The same canonical display fields feed notes and graph; Bases use Chinese formulas and `link(file.path, title)`. Questions/tasks show progress, candidates show review and evidence separately, experiments show actual run state separately from scientific interpretation. Run display labels may be provided by `data/run-labels.json`; the archived run intent stays unchanged.

Basic Memory path changes must update both config and database through the upstream `project move` interface; changing config alone can leave an existing index rooted at the outer vault. `reindex` configures and verifies owned project paths before scanning. Default `search` is one project; `--all-enabled` excludes examples; `--include-examples` opts in. The BM adapter translates full Obsidian path prefixes into explicit BM project references for strict link resolution. Cross-project graph assertions remain canonical when the pinned BM target-write guard cannot store them.

The migration plan and before-images are under `data/migrations/structure_*/`. An applied migration is not idempotently replayable. `structure-rollback --file <exact-plan>` is allowed only if current files match its before/after images; subsequent edits must be reconciled first. Offline Obsidian workspace backups are in `runtime/structure-obsidian-before`. Indexes can be rebuilt from canonical files. Recovery never starts experiments.

Actual fresh Codex-task hooks/MCP loading must be observed on the host. A standalone MCP client, synthetic session ID or a CLI resume is not proof of automatic host activation. Keep that status separate from real Obsidian acceptance and from the fourteen-day field study.
