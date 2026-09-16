from __future__ import annotations

import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid
import psutil
from .storage import Store, Conflict, now, read_json, write_json, atomic, encode, digest, file_hash, safe_id


TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def identity(pid):
    process = psutil.Process(pid)
    return {"pid": pid, "created_at": process.create_time()}


def same_process(value):
    if not value:
        return False
    try:
        process = psutil.Process(value["pid"])
        return abs(process.create_time() - value["created_at"]) < 0.01 and process.is_running()
    except (psutil.Error, KeyError):
        return False


class Runs:
    def __init__(self, store: Store):
        self.store = store
        self.root = store.config.directory("runs")

    def path(self, run_id):
        return self.root / safe_id(run_id)

    def state(self, run_id):
        folder = self.path(run_id)
        intent = read_json(folder / "intent.json")
        if not intent:
            raise ValueError("Unknown run")
        receipt = read_json(folder / "result.json")
        if receipt:
            if receipt["intent_hash"] != digest(encode(intent)):
                return {"run_id": run_id, "status": "unknown", "reason": "receipt_intent_mismatch"}
            changed = []
            for name, expected in receipt.get("artifacts", {}).items():
                p = folder / name
                if not p.is_file() or file_hash(p) != expected:
                    changed.append(name)
            for name, expected in receipt.get("log_hashes", {}).items():
                p = folder / name
                if not p.is_file() or file_hash(p) != expected:
                    changed.append(name)
            return {"run_id": run_id, "status": receipt["status"], "exit_code": receipt.get("exit_code"),
                    "artifact_drift": changed, "scientific_outcome": "not_assessed", "result": str(folder / "result.json")}
        started = read_json(folder / "started.json", {})
        supervisor = read_json(folder / "supervisor.json", {})
        active = same_process(started.get("process")) or same_process(supervisor.get("process"))
        return {"run_id": run_id, "status": "running" if active else "unknown",
                "reason": "verified_process_identity" if active else "no_completion_receipt_or_matching_process",
                "intent": str(folder / "intent.json")}

    def reconcile(self, workstream=None, project=None):
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        results = []
        for path in sorted(self.root.glob("run_*/intent.json")):
            intent = read_json(path)
            if (workstream is None or projects.run_workstream(intent) == workstream) and (project is None or projects.run_project(intent) == project):
                value = self.state(intent["run_id"])
                if projects.active:
                    value.update(research_project_id=projects.run_project(intent),
                                 title=read_json(self.store.data / 'run-labels.json', {}).get(intent['run_id'], intent["spec"]["purpose"]), created_at=intent["created_at"])
                results.append(value)
        return results

    def prepare(self, spec):
        if not self.store.config.value["enabled"]:
            raise RuntimeError("Critical actions require recording enabled")
        for key in ("request_id", "workstream_id", "purpose", "argv", "inputs", "parameters", "resources"):
            if key not in spec:
                raise ValueError(f"Missing run field: {key}")
        if not isinstance(spec["argv"], list) or not spec["argv"] or not all(isinstance(a, str) for a in spec["argv"]):
            raise ValueError("argv must be a nonempty array; no shell command string")
        safe_id(spec["workstream_id"])
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        owner = projects.context(spec.get("research_project_id"), spec["workstream_id"], spec.get("session_id")) if projects.active else None
        run_id = "run_" + digest(encode([self.store.config.project_id, spec["request_id"]]))[:32]
        folder = self.path(run_id)
        spec_hash = digest(encode(spec))
        with self.store.lock("runs"):
            old = read_json(folder / "intent.json")
            if old:
                if old["spec_hash"] != spec_hash:
                    raise Conflict("Run request ID reused with different parameters")
                return old, False
            for path in self.root.glob("run_*/intent.json"):
                other = read_json(path)
                if set(other["spec"]["resources"]) & set(spec["resources"]):
                    state = self.state(other["run_id"])
                    if state["status"] not in TERMINAL:
                        raise Conflict(f"Resource occupied or uncertain: {state}")
            inputs = {}
            for name in spec["inputs"]:
                path = self.store.config.input_path(name)
                inputs[str(path.relative_to(self.store.config.root)) if path.is_relative_to(self.store.config.root) else str(path)] = file_hash(path)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "artifacts").mkdir(exist_ok=True)
            code_root = self.store.config.input_path(spec.get("code_root", "."))
            git = {}
            for key, args in {"head": ["rev-parse", "HEAD"], "status": ["status", "--porcelain=v1", "--", "."], "diff": ["diff", "HEAD", "--binary", "--", "."]}.items():
                result = subprocess.run(["git", "-C", str(code_root), *args], capture_output=True, timeout=20)
                git[key] = result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else None
            atomic(folder / "code.diff", (git.pop("diff") or "").encode("utf-8"))
            intent = {"run_id": run_id, "project_id": self.store.config.project_id,
                      "workstream_id": spec["workstream_id"], "spec": spec, "spec_hash": spec_hash,
                      "input_hashes": inputs, "git": git, "created_at": now(), "cwd": str(folder),
                      "environment": {"python": sys.version, "platform": platform.platform(), "executable": sys.executable},
                      "scientific_outcome": "not_assessed"}
            if projects.active:
                intent["research_project_id"] = owner
            self.store.capture({"source": "run-wrapper", "source_id": run_id + ":intent", "session_id": spec.get("session_id", "run-wrapper"),
                                "workstream_id": spec["workstream_id"], "kind": "run_intent", "author": "operator",
                                "payload": intent, "occurred_at": intent["created_at"], "completeness": "durable_intent"})
            write_json(folder / "intent.json", intent)
            return intent, True

    def start(self, spec, background=False):
        intent, fresh = self.prepare(spec)
        if not fresh:
            return dict(self.state(intent["run_id"]), reused=True, executed=False)
        if background:
            flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
            folder = self.path(intent["run_id"])
            with (folder / "supervisor.log").open("ab", buffering=0) as log:
                process = subprocess.Popen([sys.executable, "-m", "research_memory.cli", "--root", str(self.store.config.root), "worker", intent["run_id"]],
                    cwd=folder, env=self.store.config.environment(), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=flags, start_new_session=os.name != "nt")
            return {"run_id": intent["run_id"], "status": "starting", "supervisor_pid": process.pid}
        return self.execute(intent["run_id"])

    def execute(self, run_id):
        folder = self.path(run_id)
        with self.store.lock("worker_" + run_id):
            if (folder / "supervisor.json").exists() or (folder / "result.json").exists():
                raise Conflict("Worker already entered; never automatically re-execute an intent")
            intent = read_json(folder / "intent.json")
            if not intent:
                raise ValueError("No durable intent")
            # The credential is persisted BEFORE process creation. A crash here yields unknown, not a retry.
            write_json(folder / "supervisor.json", {"process": identity(os.getpid()), "at": now()})
            env = self.store.config.environment()
            env.update(RESEARCH_RUN_ID=run_id, RESEARCH_RUN_DIR=str(folder), RESEARCH_ARTIFACT_DIR=str(folder / "artifacts"))
            status, exit_code, error = "unknown", None, None
            process = None
            try:
                for name, expected in intent["input_hashes"].items():
                    if file_hash(self.store.config.input_path(name)) != expected:
                        raise Conflict(f"Input changed before execution: {name}")
                with (folder / "stdout.log").open("ab", buffering=0) as out, (folder / "stderr.log").open("ab", buffering=0) as err:
                    process = subprocess.Popen(intent["spec"]["argv"], cwd=folder, env=env,
                                               stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    started = {"run_id": run_id, "process": identity(process.pid), "started_at": now(),
                               "intent_hash": digest(encode(intent))}
                    write_json(folder / "started.json", started)
                    exit_code = process.wait()
                    os.fsync(out.fileno())
                    os.fsync(err.fileno())
                    status = "completed" if exit_code == 0 else "failed"
            except KeyboardInterrupt:
                if process:
                    process.terminate()
                    process.wait(timeout=10)
                status = "interrupted"
            except Exception as exc:
                error = str(exc)
                # Spawn may already have succeeded; preserve uncertainty until its identity is checked.
                status = "unknown" if process else "failed"
            artifacts = {str(p.relative_to(folder)): file_hash(p) for p in (folder / "artifacts").rglob("*") if p.is_file()}
            result = {"run_id": run_id, "status": status, "exit_code": exit_code, "error": error,
                      "finished_at": now(), "artifacts": artifacts, "intent_hash": digest(encode(intent)),
                      "log_hashes": {name: file_hash(folder / name) for name in ("stdout.log", "stderr.log") if (folder / name).exists()},
                      "scientific_outcome": "not_assessed"}
            if status != "unknown":
                write_json(folder / "result.json", result)
                self.store.capture({"source": "run-wrapper", "source_id": run_id + ":result", "session_id": intent["spec"].get("session_id", "run-wrapper"),
                    "workstream_id": intent["workstream_id"], "kind": "run_finished", "author": "tool", "payload": result,
                    "occurred_at": result["finished_at"], "completeness": "receipt"})
            else:
                write_json(folder / "uncertainty.json", result)
            return result

    def resolve(self, run_id, status, evidence):
        if status not in TERMINAL or not evidence:
            raise ValueError("Resolution requires explicit terminal status and evidence")
        folder = self.path(run_id)
        with self.store.lock("runs"):
            current = self.state(run_id)
            if current["status"] != "unknown":
                raise Conflict("Only an unknown run can be reconciled manually")
            intent = read_json(folder / "intent.json")
            result = {"run_id": run_id, "status": status, "intent_hash": digest(encode(intent)),
                      "resolution_evidence": evidence, "resolved_at": now(), "scientific_outcome": "not_assessed"}
            write_json(folder / "result.json", result)
            return result
