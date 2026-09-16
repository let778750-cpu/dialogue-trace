# Recording, interpretation and typed inspection

[中文](../references/capture-and-trajectory.md) · [Home](../README.md)

Raw archival is deterministic local I/O. The skill governs entry, reconciliation, bounded recovery and semantic publication; it is not a resident process. Installing its instructions does not prove that the host trusts or invokes hooks.

| Task | Mechanism | Model cost |
|---|---|---|
| Preserve public messages, tool inputs/results, source locations and hashes | Observed hooks or an explicitly selected transcript | No additional model request |
| Recognize complete environment envelopes, pair unique call IDs and build indexes | Rules and versioned projections | No additional model request |
| Interpret workstreams, significance, contradictions and next steps | Current session model, in batches | Context and generation cost |
| Resume | Revision check, then bounded deltas | Depends on information read |

A second low-cost model continuously re-reading the conversation would duplicate context and introduce review, omission, concurrency and credential overhead. This release does not start one. A future optional batch organizer should produce source-backed candidates, never replace factual archival or publish conclusions automatically.

The official [skill structure](https://learn.chatgpt.com/docs/build-skills) does not declare a resident recording model. [Hooks](https://learn.chatgpt.com/zh-Hans/docs/hooks) have their own trust and execution requirements; transcript formats can change.

## What comes from Harness

Design references: [Trajectory](https://github.com/deepseek-ai/deepseek-harness/blob/0d1f50007f9bca3f52b06e1c3074fa14d5fb0720/packages/client/ui-trajectory/README.md) and [session projection architecture](https://github.com/deepseek-ai/deepseek-harness/blob/0d1f50007f9bca3f52b06e1c3074fa14d5fb0720/.agents/notes/archived/architecture/2026-08-11-trajectory-conversation-context-assembly.md). No implementation code was copied.

- One event source serves the research timeline and technical inspector.
- User, assistant, context, tool and lifecycle events have different inspection structures.
- Tool inputs, results, definitions and timing remain separate. Duplicate call IDs are ambiguous, not proof of a unique parent.
- Long technical bodies load on demand; source fields and readable previews remain distinct.
- Unrecorded timing, token usage or schema is unknown. Ingestion delay is not execution duration.
- Stable reading anchors and incremental loading keep new records from taking over the current position.

Harness controls the provider request lifecycle and can expose more request-level metadata. This adapter consumes only public fields actually available from Codex. It does not collect hidden reasoning; compaction stores a lifecycle boundary rather than internal prompts or private summaries. Research checkpoints are separately published, readable records of known facts, unknowns and next steps.
