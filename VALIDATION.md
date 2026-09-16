# Validation: 0.8.0-preview.2

[简体中文](VALIDATION.zh-CN.md) · [Home](README.md)

Test date: **2026-09-17 (Asia/Shanghai)**. This is an installable preview. Engineering checks and a bounded real Obsidian walkthrough passed; live host capture coverage and human research outcomes remain separate acceptance gates.

## Verified

| Check | Observed result and scope |
|---|---|
| Packaged Python regression | **133 passed, 55.13 seconds**, using an independently installed CPython 3.12.11 runtime on Windows. |
| JavaScript regression | **37 passed**. Covers reader logic, contracts and compatibility; this is not a browser end-to-end suite. |
| Fresh online installation | **7/7 passed**, with no reused download cache. Chinese and space-containing paths, repeated setup, diagnostics, identity retention, optional Obsidian, independent code/runtime and uninstall preserving data. One successful network path does not guarantee universal download availability. |
| Upgrade and integration | **9/9 passed**: upgrade, preserved data/identity, packaged Python/JS suites, synthetic demo, optional component installation and repeat, reading state retention, independent stdio MCP. |
| Actual Obsidian | **1.13.7**, isolated synthetic vault: opening, narrow single column and wide alternating lanes, technical/environment records outside the main timeline, separate tool input/result/timing tabs, checkpoint details and source jump, wide reading with rendered table. Homepage screenshots are from this actual application. |
| New-install defect | Real UI exposed a missing vault identity file. Initialization now creates it, repeat setup retains it, and a conflicting project identity is rejected without replacement. Regression tests included. |
| Reliability | Automated cases cover concurrent writers, stable request replay, version conflicts, undo, delayed tool results, ambiguous call IDs, historical boundaries, source checks and read receipts. |
| Source preservation | The prior implementation compared 2,485 protected event, knowledge and vault files unchanged before appending new session records. Publication uses an explicit public file set and no private Git history. |

Screenshots use a **synthetic bilingual thermal-drift example**, including illustrative tool output. They establish rendering, not an experimental conclusion or live dual-task collection. UI controls currently use Chinese; the homepage, install guide and validation report have English and Chinese editions.

## Performance and historical pilot

The earlier 10,000-event benchmark alternated the 0.7 baseline and 0.8 projection code for 11 rounds on one Windows machine (Intel Core Ultra 9 275HX): median **108.91 ms / 100.01 ms**, ratio **0.918**. This measures in-memory projection construction only. It excludes disk publication, first paint, append loading, interactive search and human reading time. This is inherited evidence, not a complete performance rerun for this documentation/installer update.

A private isolated pilot prepared 12 complete message ranges from two real historical tasks covering cross-task work, mixed topics, shared evidence and uncertainty. **Zero routing changes were applied.** Private pilot data is excluded from this repository.

## Pending and known limitations

- Two **simultaneously active real Codex tasks** have not completed hook, per-turn resume and correction acceptance. Transcript replay and process concurrency do not establish this.
- The real Obsidian walkthrough above is bounded. A complete theme, attachment, project-switch and 10,000-event interaction matrix remains pending.
- Human retrieval outcomes have not been timed. Report the original six retrieval tasks and five new continuation/organization tasks separately. The target remains a **20% lower median completion time** versus the best comparable baseline, without worse source accuracy. It is not an achieved result.
- Skill installation is not a resident listener or proof that hooks execute. Only accessible public source material is archived; unavailable timing, token, turn and hierarchy fields remain unknown.
- No background model, hidden reasoning capture, DeepSeek Harness host adapter or automatic experiment resumption is included. No macOS/Linux support claim is made.

## Reproduce and inspect

After installing the locked dependencies:

```powershell
python -m pytest tests -q
node --test (Get-ChildItem tools/obsidian/graph/*.test.cjs).FullName
python scripts/check_release.py
python scripts/build_obsidian.py --output build/obsidian
python scripts/showcase.py --root "$env:TEMP/research-memory-example" --with-obsidian
```

Choose a new example directory: the demo refuses to overwrite an existing instance. GitHub Actions runs regression, integrity, build and synthetic-case checks on Windows. Cloud results appear in the Actions tab; local results must not be mistaken for an unobserved cloud run.

`release-manifest.json` lists source file SHA-256 hashes. Release ZIPs have a separate `SHA256SUMS.txt`. Component licenses and build inputs are included. Private conversations, credentials, personal paths, logs and real research libraries are excluded. Homepage images contain only the synthetic case.

See [acceptance procedure](references/acceptance.md), [recording boundaries](docs/RECORDING.md), and [demo/video instructions](docs/DEMO.md).
