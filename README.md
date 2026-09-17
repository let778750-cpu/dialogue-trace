# dialogue-trace

**English** · [简体中文](README.zh-CN.md) · [Quick start](#quick-start) · [Example](#continuing-a-question-across-tasks) · [Download](https://github.com/let778750-cpu/dialogue-trace/releases/tag/v0.8.0-preview.3)

dialogue-trace is a research memory tool for Codex. It organizes discussions from separate tasks around the questions you are investigating, preserves the original messages and evidence, and helps you recover earlier decisions when you return to the work.

It is intended for projects where an explanation or experimental plan changes through discussion and testing. You might design an experiment in one task and discover a missing control in another. Keeping those discussions in the same research workstream lets you trace why the plan changed without searching each chat separately.

The project installs as a **Codex skill**, a package of instructions and local programs that Codex uses to record and organize research. You can use the core workflow within Codex. Add Obsidian if you would also like to browse the timeline shown below.

![Reading research discussions in order in Obsidian](assets/screenshots/timeline-light.jpg)

This is an actual Obsidian screenshot of the synthetic thermal-drift example included with the project. Blue cards contain user messages; purple cards contain AI responses. The reader switches to a single column in narrow windows. The current preview supports Codex on Windows. Reader controls are in Chinese, and documentation is available in English and Chinese.

## Quick start

You will need Codex and Python 3.12 or later, available through `python --version` in PowerShell. Initialization also needs a network connection to download dependencies. Obsidian can be added later; Node.js is only required for development.

### 1. Install the skill

Send this request to Codex:

```text
Use skill-installer to install the repository root from
https://github.com/let778750-cpu/dialogue-trace as a skill named dialogue-trace.
Tell me the installation directory when it is ready.
```

For a manual installation, download [dialogue-trace-0.8.0-preview.3.zip](https://github.com/let778750-cpu/dialogue-trace/releases/download/v0.8.0-preview.3/dialogue-trace-0.8.0-preview.3.zip) and place the extracted `dialogue-trace` folder in your Codex skills directory. The default is `.codex\skills` under your user directory, or the `skills` folder under `CODEX_HOME` if you have set it. Keep the entire folder: the instructions in `SKILL.md` depend on the programs included in the package.

### 2. Initialize storage for your project

Open PowerShell in the installed `dialogue-trace` folder. The example below uses `C:\Research\SensorDrift` for the project and `C:\ResearchData\SensorDrift` for its private data. Replace both paths with your own locations. The project directory must already exist; initialization creates the data directory, which must be outside the skill installation.

```powershell
.\scripts\install.ps1 -Workspace 'C:\Research\SensorDrift' -DataDir 'C:\ResearchData\SensorDrift'
.\scripts\memory.ps1 --root 'C:\ResearchData\SensorDrift' doctor
```

The project directory contains the code and materials you work with. The separate data directory holds source records, organized knowledge and the local runtime, and remains in use when you upgrade the program. Initialization downloads the pinned Python runtime and dependencies, then configures integration for the project you specified.

The `doctor` command reports paths, registered workspaces, dependency versions and capture status. Check that the paths are correct and no dependency is marked `not_installed`. A fresh installation may show `hooks.state` as `not_observed`: this means no host capture callback has been observed yet. It does not indicate an installation failure, but you should check that records arrive when you begin using the skill.

### 3. Record your first discussion

Open a new Codex task in the registered project directory. Adapt this request to your question and data location:

```text
Use $dialogue-trace with the data directory C:\ResearchData\SensorDrift.
Create a research workstream for whether rising temperature causes sensor drift,
and record this discussion. Start with the conditions we know, then leave the
unanswered questions and next experiment when we finish.
```

Codex should identify the workstream before recording and organizing the discussion. Continue by adding experimental conditions, comparing explanations or examining results. Before you finish, ask it to report what was saved and provide the source references. This also gives you a way to check that the discussion was recorded correctly.

When you return, name the workstream explicitly: “Continue the temperature-and-drift question.” If the host has not supplied readable messages, Codex should report the gap; you can ask it to reconcile the task's available transcript. Installing the skill alone does not guarantee that every turn has been archived.

See the [installation and maintenance guide](references/installation.md) for interrupted downloads, existing configurations and upgrades.

## Read the timeline in Obsidian

After initialization, run this command from the skill directory:

```powershell
.\scripts\memory.ps1 --root 'C:\ResearchData\SensorDrift' attach-obsidian
```

It installs the reader component into this instance's vault. Install Obsidian separately, open `C:\ResearchData\SensorDrift\vault`, review its trust prompt and enable the component. Then use the command palette to run **打开研究时间线** (“Open research timeline”). The timeline works on its own. Install Juggl 1.5.0 later if you need the optional local knowledge graph.

The reader preserves the discussion's source order. Long answers can be expanded or opened in a wider reading view, and important results and checkpoints link back to their source messages. Command output and environment information are available in technical details, keeping them out of the main reading path.

## Continuing a question across tasks

A **project** defines the scope of the work. A **workstream** follows a research question over time. A **task** is a Codex conversation that supplies source messages. Several tasks can contribute to the same workstream, and a single task can discuss several workstreams.

Consider the thermal-drift example. In the first task, you suggest that rising temperature may explain sensor drift, then add that warm-up time has not been controlled. That condition changes the experimental plan: establish thermal stability before comparing drift. When you return in another task a few days later, you can recover that revision before deciding which repeated trials are still needed.

If the discussion moves to a separate question, such as choosing measurement equipment, ask Codex to create another workstream. Existing messages can be reassigned as complete, consecutive ranges while retaining their original sources. Another workstream can reference the same evidence. Uncertain assignments remain for review, and browsing a workstream does not change the current task's binding.

The research checkpoint below brings together known conditions, open questions and the next step, with a link to the original message. It records where the research stands; it does not imply that a file exists from which a computation can resume.

![A research checkpoint with known conditions, open questions and a next step](assets/screenshots/checkpoint.jpg)

To investigate a result, open the tool details and inspect its arguments, returned output and source information separately. A successful run establishes that the program completed. Whether its result supports a research conclusion still requires interpretation and verification.

![Inspecting a tool result and its source on demand](assets/screenshots/tool-details.jpg)

### Try the example from the screenshots

Once initialization is complete, run the following from the skill directory. Adjust the Python path if you used a different data location. Choose a new demo directory; the script refuses to overwrite an existing instance.

```powershell
& 'C:\ResearchData\SensorDrift\runtime\venv\Scripts\python.exe' .\scripts\showcase.py --root 'C:\ResearchData\DialogueTraceDemo' --with-obsidian
```

Open `C:\ResearchData\DialogueTraceDemo\vault` in Obsidian, enable the component and open the timeline. The example contains two source tasks and a research checkpoint. All messages and tool values are synthetic demonstration material; the script does not read your private conversations or execute a scientific experiment.

### Video walkthrough

A video will be added after recording. Until then, the steps above reproduce the same example. See the [demo guide](docs/DEMO.md) for recording instructions and how to add the video.

## Recording and model cost

Local scripts preserve public messages and tool records, remove duplicate imports, track sources and build indexes. These operations do not make additional model requests. The current Codex model handles interpretation in batches, including workstream suggestions, the significance of a result and the next question to investigate. That work still consumes context and generated tokens.

The project does not run a second model that continuously rereads the conversation. Original records are stored separately from interpretations, AI summaries retain source references, and organization can be corrected with its history preserved. Automatic capture is scoped to registered workspaces and tasks that have explicitly entered the research workflow.

The archive is limited to public messages, public progress explanations and tool records supplied by the host. It does not collect hidden reasoning or private internal compaction summaries. Missing timing, token counts or call hierarchy remain unknown. The [recording guide](docs/RECORDING.md) explains these boundaries in more detail.

## Validation status

This is a preview release. Validation includes 133 Python tests, 37 JavaScript tests, independent installation and upgrade checks, and a limited walkthrough in the actual Obsidian application. See the [validation report](VALIDATION.md) for results and reproduction conditions. Checks for subsequent commits appear in [GitHub Actions](https://github.com/let778750-cpu/dialogue-trace/actions).

The remaining acceptance work includes reliable capture and continuation across two simultaneously active Codex tasks, the full reader performance matrix and human retrieval tasks. The existing tests do not establish a reduction in research time. Those usage scenarios need to be evaluated before replacing an established daily workflow.

## Development

The Python backend is in `src`; the Obsidian component source is in `tools/obsidian/graph/plugin`. The [contributing guide](CONTRIBUTING.md) covers environment setup and checks, and the [API reference](references/research-api.md) describes backend operations. When reporting an [issue](https://github.com/let778750-cpu/dialogue-trace/issues), include the version, reproduction steps and observed behavior. Synthetic examples are sufficient to illustrate a problem.

## License and acknowledgments

Original project code is licensed under [AGPL-3.0](LICENSE). The existing Obsidian adapter retains GPL-3.0, and third-party components retain their own notices; see [THIRD_PARTY.md](THIRD_PARTY.md) for the scope. The Obsidian application is not included in the distribution.

The project uses Python, Basic Memory and FastMCP, with an optional Obsidian reader. Its tool inspector draws on DeepSeek Harness Trajectory's approach to typed records, documented in the [design references](docs/RECORDING.md#what-comes-from-harness). No Harness implementation code was copied, and a Harness host adapter is not currently provided.
