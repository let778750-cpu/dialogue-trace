import sqlite3
import pytest
from research_memory.storage import Store, atomic, write_json, read_json, file_hash
from research_memory.continuity import Continuity
from research_memory.basic_memory import search
from research_memory.capture import Transcript
from research_memory.runs import Runs
from research_memory.knowledge import Knowledge
from test_continuity_runs import spec
from test_knowledge import note


def test_corrupt_catalog_can_be_rebuilt_from_files(store, event):
    event_id = store.capture(event)
    store.acknowledge([event_id], "fixture", [], "fully reviewed")
    atomic(store.db_path, b"THIS IS NOT SQLITE")
    damaged = Store(store.config)
    with pytest.raises(sqlite3.DatabaseError):
        damaged.capture(dict(event, source_id="captured-while-index-broken"))
    recovered = Store(store.config, recover=True)
    assert recovered.status()["captured"] == 2
    assert recovered.status()["organized"] == 1
    assert list((store.data / "quarantine").glob("*catalog.sqlite"))


def test_unknown_source_schema_gap_does_not_disappear_on_poll(store):
    path = store.config.root / "host.jsonl"
    atomic(path, b'{"type":"future_public_record","payload":{}}\n')
    adapter = Transcript(store)
    assert adapter.ingest(path, "fixture", "system-development")["state"] == "gap"
    assert adapter.ingest(path, "fixture", "system-development")["state"] == "gap"


def test_missing_experiment_log_is_reported(store):
    runner = Runs(store)
    result = runner.start(spec())
    (runner.path(result["run_id"]) / "stdout.log").unlink()
    assert "stdout.log" in runner.state(result["run_id"])["artifact_drift"]


def test_non_supporting_retrieval_cannot_verify_quote(store, event):
    source_id = store.capture(dict(event, kind="source", payload={"url": "https://example.org/paper", "text": "An unrelated result."}))
    n = note(source_id)
    n["type"] = "evidence"
    n["sources"] = [{"event_id": source_id}]
    n["evidence"] = {"url": "https://example.org/paper", "locator": "abstract", "excerpt": "The hypothesis is proven",
                     "access_level": "abstract_only", "verification": "verified", "checked_source_event": source_id}
    with pytest.raises(ValueError, match="excerpt"):
        Knowledge(store).save(n)


def test_repair_preserves_ingestion_order_without_inventing_source_order(store, event):
    a = store.capture(dict(event, source_id="late-source", source_sequence=5))
    b = store.capture(dict(event, source_id="earlier-backfill", source_sequence=1))
    store.repair()
    pending = store.pending()
    assert [e["event"]["event_id"] for e in pending] == [a, b]
    assert [e["event"]["source_sequence"] for e in pending] == [5, 1]


def test_human_note_edit_invalidates_index_health(store):
    note_path = store.config.directory("vault") / "manual.md"
    atomic(note_path, b"first version")
    write_json(store.data / "health/index.json", {"state": "ready", "indexed_files": {"manual.md": file_hash(note_path)}})
    assert store.status()["index"]["state"] == "ready"
    atomic(note_path, b"changed by human")
    assert store.status()["index"]["state"] == "stale"


def test_new_session_in_child_directory_inherits_branch(store):
    continuity = Continuity(store)
    continuity.bind(store.config.root, "old-session")
    result = continuity.bind(store.config.root / "src", "new-session")
    assert result["workstream_id"] == "system-development"


def test_unknown_item_schema_is_persistently_reported(store):
    path = store.config.root / "future.jsonl"
    atomic(path, b'{"type":"response_item","payload":{"type":"future_tool_result"}}\n')
    adapter = Transcript(store)
    assert adapter.ingest(path, "fixture", "system-development")["issues"][0]["kind"] == "unknown_item_type"
    assert adapter.ingest(path, "fixture", "system-development")["state"] == "gap"


def test_cross_project_request_cannot_silently_search_current_project(store):
    with pytest.raises(ValueError, match="project-scoped"):
        search(store.config, "example", project="unregistered-project")
