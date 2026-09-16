"""Research ownership is independent of the immutable archive namespace and windows."""
from copy import deepcopy
from pathlib import PurePosixPath

from .storage import Conflict, Store, atomic, now, read_json, safe_id, write_json

REGISTRY = "research-projects.json"
OWNERSHIP = "project-ownership.json"
SYSTEM = "系统视图"
HOME = "科研工作台.md"
TYPE_FOLDERS = {"question": "问题", "idea": "候选想法", "evidence": "证据", "experiment": "实验", "task": "验证任务", "decision": "决策"}


class ResearchProjects:
    def __init__(self, config, value=None, ownership=None):
        self.config = config
        self.vault = config.directory("vault")
        self.file = config.directory("data") / REGISTRY
        self.value = value if value is not None else read_json(self.file)
        self.ownership = ownership if ownership is not None else read_json(config.directory("data") / OWNERSHIP, {"version": 0, "notes": {}, "events": {}, "runs": {}})
        from .research import read_state
        self.research_state = read_state(config)
        self.call_owners = read_json(config.directory('data') / 'call-ownership.json', {})

    @property
    def active(self):
        return self.value is not None

    @property
    def default(self):
        return self.value["default_project_id"] if self.active else self.config.project_id

    def records(self, examples=False, disabled=False):
        if not self.active:
            return [{"id": self.default, "name": "科研记忆系统", "path": "", "kind": "research", "enabled": True, "bm_project": self.default, "goal": ""}]
        return [deepcopy(p) for p in self.value["projects"].values()
                if (examples or p["kind"] == "research") and (disabled or p["enabled"])]

    def get(self, project=None, disabled=False):
        project = project or self.default
        for p in self.records(examples=True, disabled=disabled):
            if p["id"] == project:
                return p
        raise ValueError("Unknown or disabled research project: " + str(project))

    def folder(self, project=None):
        p = self.get(project, disabled=True)
        path = self.vault / p["path"]
        if not path.resolve().is_relative_to(self.vault.resolve()):
            raise ValueError("Research project path escapes vault")
        return path

    def branch_project(self, workstream=None):
        if not self.active:
            return self.default
        return self.value.get("branches", {}).get(workstream, self.default)

    def context(self, project=None, workstream=None, session=None):
        """An explicit session/branch cannot be silently reassigned by a project flag."""
        if not self.active:
            return self.default
        registry = read_json(self.config.directory("data") / "registry.json", {})
        bound = registry.get("sessions", {}).get(session)
        if bound and workstream and bound != workstream:
            # bind is the explicit interface for switching a session; writes must match it.
            raise Conflict("Session belongs to a different research branch")
        selected = workstream or bound
        owner = self.value.get("branches", {}).get(selected)
        if project and owner and project != owner:
            raise Conflict("Research project and branch disagree")
        if selected and owner is None:
            raise ValueError("Research branch must be registered before recording: " + selected)
        return self.get(project or owner or self.default)["id"]

    def note_project(self, note):
        return note.get("research_project_id") or self.ownership.get("notes", {}).get(note["id"]) or self.branch_project(note.get("workstream_id"))

    def event_project(self, event):
        return event.get("research_project_id") or self.ownership.get("events", {}).get(event.get("event_id")) or self.branch_project(event.get("workstream_id"))

    def run_project(self, intent):
        return intent.get("research_project_id") or self.ownership.get("runs", {}).get(intent["run_id"]) or self.branch_project(intent.get("workstream_id"))

    def event_workstream(self, event):
        from .research import effective_branch
        fallback = self.ownership.get("event_workstreams", {}).get(event.get("event_id"), event.get("workstream_id"))
        call = event.get('payload', {}).get('call_id') or event.get('payload', {}).get('tool_use_id')
        if event.get('kind') == 'tool_result' and event.get('event_id') not in self.research_state['assignments']:
            from .storage import digest, encode
            key = digest(encode([event.get('session_id'), call]))
            if call and key in self.call_owners:
                return self.call_owners[key]
        return effective_branch(event, fallback, self.research_state)

    def run_workstream(self, intent):
        return self.ownership.get("run_workstreams", {}).get(intent["run_id"], intent.get("workstream_id"))

    def branch_name(self, workstream):
        registry = read_json(self.config.directory("data") / "registry.json", {})
        branch = registry.get("branches", {}).get(workstream, {})
        return branch.get("name") or branch.get("goal") or ("系统设计与开发" if workstream == "system-development" else workstream)

    def add_branch(self, workstream, project):
        if not self.active:
            return
        self.get(project)
        store = Store(self.config)
        with store.lock("research-projects"):
            value = read_json(self.file)
            old = value.setdefault("branches", {}).get(workstream)
            if old and old != project:
                raise Conflict("A research branch cannot belong to two projects")
            value["branches"][workstream] = project
            value["version"] += 1
            write_json(self.file, value)
            self.value = value

    def register(self, project, name, goal="", kind="research", enabled=True, expected_version=None):
        if not self.active:
            raise ValueError("Run the structure migration before registering research projects")
        safe_id(project)
        if project == self.default and not enabled:
            raise ValueError('Use set-enabled false to disable the archive including its default project')
        if kind not in {"research", "example"}:
            raise ValueError("Project kind must be research or example")
        from .readability import clean_name
        if not name or clean_name(name) != name:
            raise ValueError("Use a readable Windows-compatible project name of at most 64 characters")
        store = Store(self.config)
        with store.lock("research-projects"):
            value = read_json(self.file)
            if expected_version is not None and value["version"] != expected_version:
                raise Conflict("Research project registry version changed")
            old = value["projects"].get(project)
            path = old["path"] if old else ("研究项目/" if kind == "research" else "示例与验收/") + name
            if any(p["id"] != project and p["path"].casefold() == path.casefold() for p in value["projects"].values()):
                raise Conflict("A project with this folder name already exists")
            target = self.vault / path
            if not target.resolve().is_relative_to(self.vault.resolve()):
                raise ValueError("Project path escapes vault")
            if old and old["kind"] != kind:
                raise Conflict("Changing a project's category requires a reviewed migration")
            p = dict(old or {}, id=project, name=name, path=path, goal=goal, kind=kind,
                     enabled=enabled, bm_project=(old or {}).get("bm_project", project), updated_at=now())
            value["projects"][project] = p
            value["version"] += 1
            write_json(store.data / "project-registry-history" / (str(value["version"]) + ".json"), value)
            write_json(self.file, value)
            self.value = value
        self.scaffold(project)
        return p

    def scaffold(self, project):
        # Atomic file publication creates descendants when they have content.
        # Keep the project root for its index, without an empty taxonomy tree.
        self.folder(project).mkdir(parents=True, exist_ok=True)

    def set_graph_entries(self, project, entries, expected_version, workstream=None):
        """Reading entry points are explicit registry metadata, never inferred scientific roots."""
        from .knowledge import Knowledge
        self.get(project)
        store = Store(self.config)
        entries = list(dict.fromkeys(safe_id(x) for x in entries))
        with store.lock("research-projects"), store.lock("knowledge"):
            value = read_json(self.file)
            if value["version"] != expected_version:
                raise Conflict("Research project registry version changed")
            if workstream and value["branches"].get(workstream) != project:
                raise ValueError("Entry branch does not belong to project")
            notes = {n["id"]: n for n in Knowledge(store).records()}
            for id in entries:
                n = notes.get(id)
                if not n or n["type"] != "question" or self.note_project(n) != project or (workstream and n["workstream_id"] != workstream):
                    raise ValueError("An entry must be an existing question in the selected project/branch: " + id)
            p = value["projects"][project]
            if workstream:
                p.setdefault("graph_branch_entries", {})[workstream] = entries
            else:
                p["graph_entry_ids"] = entries
            value["version"] += 1
            write_json(store.data / "project-registry-history" / (str(value["version"]) + ".json"), value)
            write_json(self.file, value)
            self.value = value
        return {"project": project, "workstream": workstream, "entry_ids": entries, "version": value["version"]}

    def validate_path(self, path):
        path = str(path).replace("\\", "/")
        parts = PurePosixPath(path).parts
        if not parts or PurePosixPath(path).is_absolute() or any(not p or p in {".", ".."} or p.startswith(".") or p.rstrip(" .") != p or
                            any(c in p for c in ':*?"<>|') or any(ord(c) < 32 for c in p) for p in path.split("/")):
            raise ValueError("Invalid research view path")
        if not (self.vault / path).resolve().is_relative_to(self.vault.resolve()):
            raise ValueError("Research path escapes vault")
        return path


def initial_catalog(config, notes, events, intents):
    main = config.project_id
    sample = "sample-synthetic-noise"
    project = lambda id, name, kind, goal, enabled=True: dict(id=id, name=name, kind=kind, goal=goal, enabled=enabled,
        path=("研究项目/" if kind == "research" else "示例与验收/") + name, bm_project=id)
    value = {"schema_version": 1, "version": 1, "default_project_id": main, "branches": {"system-development": main, sample + "-main": sample},
             "projects": {
                 main: project(main, "科研记忆系统", "research", "保存双方研究分支、关联证据并可靠恢复实验状态"),
                 sample: project(sample, "合成噪声实验", "example", "演示独立运行与结果溯源，不构成真实科研结论"),
                 "routing-acceptance": project("routing-acceptance", "项目路由验收", "example", "已停用的检索隔离验收样本", False)}}
    ownership = {"schema_version": 1, "version": 1, "at": now(), "notes": {}, "events": {}, "runs": {}, "event_workstreams": {}, "run_workstreams": {}}
    for n in notes:
        owner = sample if n["id"] in {"experiment-synthetic-noise", "evidence-synthetic-metrics"} else main
        ownership["notes"][n["id"]] = owner
        if owner == sample:
            for s in n.get("sources", []):
                ownership["events"][s["event_id"]] = owner
            for run in n.get("run_ids", []):
                ownership["runs"][run] = owner
    for intent in intents:
        ownership["runs"].setdefault(intent["run_id"], main)
    for e in events:
        run = e.get("payload", {}).get("run_id") if isinstance(e.get("payload"), dict) else None
        ownership["events"].setdefault(e["event_id"], ownership["runs"].get(run, main))
    ownership["event_workstreams"] = {e: sample + "-main" for e, p in ownership["events"].items() if p == sample}
    ownership["run_workstreams"] = {r: sample + "-main" for r, p in ownership["runs"].items() if p == sample}
    return value, ownership
