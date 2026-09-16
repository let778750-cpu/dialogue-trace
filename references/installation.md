# Windows installation and recovery

Keep the downloaded skill directory outside its private data directory. The complete repository root is the skill folder; do not copy only SKILL.md. Python 3.12+ is required. A bootstrap Python creates the downloader; initialization downloads managed CPython 3.12.11 into the private runtime and installs locked dependencies. Download failures preserve the instance and can be retried; embeddings are downloaded only when requested by semantic indexing.

From the skill directory:

```powershell
./scripts/install.ps1 -Workspace 'C:/Research/MyProject' -DataDir 'C:/ResearchMemory/MyArchive'
# Optional complete reader:
./scripts/install.ps1 -Workspace 'C:/Research/MyProject' -DataDir 'C:/ResearchMemory/MyArchive' -WithObsidian
./scripts/memory.ps1 --root 'C:/ResearchMemory/MyArchive' doctor
```

Paths above are examples, not directories to scan. Initialization configures only the supplied workspace. New instances require the skill to explicitly enter a research session with `bind` before hooks archive that task; reconcile its first prompt from the selected transcript. Legacy instances keep their previously enabled capture policy until deliberately changed. Existing settings are preserved; a conflicting integration produces a specific error. The host may require reopening the task to load newly configured tools. Verify observed hooks and transcript reconciliation independently.

Open the reported vault in Obsidian and enable its installed Research Memory plugin. The timeline works without Juggl. To use the optional local graph, install and enable Juggl **1.5.0**. Obsidian itself is obtained separately. Existing user plugin settings and reading positions are retained on managed updates.

## Upgrade

Replace the skill's program files with the complete newer release, keeping the private data directory. Run `install.ps1` with the same workspace/data directory and `-Upgrade`; add `-WithObsidian` if that component is enabled. This snapshots metadata and plugin state under the instance runtime, installs fixed dependencies and updates the program location. If the code directory moved, an old managed host path may be reported as a conflict: uninstall the exact old managed entry before configuring the new one; do not overwrite unrelated settings.

Version 0.8 does not migrate raw event identities. Existing development instances keep their original root and legacy wrapper behavior. A production plugin is not replaced by the preview installer unless its installation has been deliberately registered as managed and the release gate is satisfied.

## Uninstall and recovery

Run `memory.ps1 --root <data-directory> uninstall` to remove only the host entries that still match this installation. Then remove the downloaded skill directory if desired. Research data, runtime, Obsidian plugin and reading state are retained. Keep the private archive separately backed up.

An interrupted operation retains its request ID. Read `research state` and the stored receipt; retry identical content only. Do not replay scientific runs with a new request ID. Raw events, source hashes and guarded commits remain authoritative; timeline and search indexes can be rebuilt.
