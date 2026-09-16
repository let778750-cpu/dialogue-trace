import os
import sys
import time
import pytest
from research_memory.continuity import Continuity
from research_memory.runs import Runs, same_process
from research_memory.storage import Conflict, atomic, read_json, write_json


def spec(request="exp-1", code="print('result')"):
    return {"request_id": request, "workstream_id": "system-development", "purpose": "Test prediction",
            "argv": [sys.executable, "-c", code], "inputs": [], "parameters": {"seed": 1}, "resources": ["fixture-resource"]}


def test_bind_cross_window_ambiguous_only_when_required(store):
    c = Continuity(store)
    assert c.bind(store.config.root, "day1")["workstream_id"] == "system-development"
    assert c.bind(store.config.root, "day8")["workstream_id"] == "system-development"
    c.bind(store.config.root, "other", "alternative", create=True)
    assert c.bind(store.config.root, "new")["state"] == "ambiguous"
    assert c.bind(store.config.root, "day1")["workstream_id"] == "system-development"


def test_checkpoint_cas_and_dependency_drift(store):
    c = Continuity(store)
    c.bind(store.config.root, "fixture")
    path = store.config.root / "data.csv"
    atomic(path, b"value\n1\n")
    c.checkpoint("system-development", {"goal": "Keep old unfinished work", "open_questions": ["pending since last year"], "dependencies": ["data.csv"]}, 0)
    with pytest.raises(Conflict):
        c.checkpoint("system-development", {}, 0)
    atomic(path, b"value\n2\n")
    resumed = c.resume("system-development")
    assert resumed["dependency_drift"][0]["path"] == "data.csv"
    assert "last year" in resumed["brief"]


def test_run_full_logs_artifact_independent_ids(store):
    runner = Runs(store)
    code = "import os,pathlib; print('negative result'); pathlib.Path(os.environ['RESEARCH_ARTIFACT_DIR'],'result.txt').write_text('0.1')"
    result = runner.start(spec(code=code))
    assert result["status"] == "completed"
    assert result["scientific_outcome"] == "not_assessed"
    folder = runner.path(result["run_id"])
    assert (folder / "stdout.log").read_text().strip() == "negative result"
    assert result["artifacts"]["artifacts\\result.txt"] if os.name == "nt" else result["artifacts"]["artifacts/result.txt"]
    reused = runner.start(spec(code=code))
    assert reused["executed"] is False
    assert runner.start(spec("exp-2"))["run_id"] != result["run_id"]


def test_failed_persistence_prevents_spawn(store, monkeypatch):
    monkeypatch.setattr(store, "capture", lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")))
    with pytest.raises(OSError):
        Runs(store).start(spec(code="raise Exception('should not execute')"))
    assert not list(store.config.directory("runs").glob("*/started.json"))


def test_unknown_intent_never_replayed_and_resource_blocked(store):
    runner = Runs(store)
    intent, _ = runner.prepare(spec())
    assert runner.state(intent["run_id"])["status"] == "unknown"
    assert runner.start(spec())["executed"] is False
    with pytest.raises(Conflict):
        runner.start(spec("different-id"))
    runner.resolve(intent["run_id"], "cancelled", "Verified no child was created; fixture boundary before spawn")
    assert runner.start(spec("different-id"))["status"] == "completed"


def test_input_changes_after_intent_prevent_execution(store):
    path = store.config.root / "input.txt"
    atomic(path, b"A")
    value = spec()
    value["inputs"] = ["input.txt"]
    runner = Runs(store)
    intent, _ = runner.prepare(value)
    atomic(path, b"B")
    result = runner.execute(intent["run_id"])
    assert result["status"] == "failed"
    assert not (runner.path(intent["run_id"]) / "started.json").exists()


def test_wrong_pid_birth_is_not_running():
    assert not same_process({"pid": os.getpid(), "created_at": 1.0})


def test_background_long_command_completes_after_initial_response(store):
    runner = Runs(store)
    result = runner.start(spec(code="import time; time.sleep(0.4); print('late-result')"), background=True)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        state = runner.state(result["run_id"])
        if state["status"] == "completed":
            break
        time.sleep(0.1)
    assert state["status"] == "completed"
    assert "late-result" in (runner.path(result["run_id"]) / "stdout.log").read_text()


def test_failure_is_distinct_from_process_success(store):
    result = Runs(store).start(spec(code="import sys; print('failure'); sys.exit(7)"))
    assert result["status"] == "failed" and result["exit_code"] == 7
