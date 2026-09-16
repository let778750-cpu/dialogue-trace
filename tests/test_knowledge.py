import pytest
from research_memory.knowledge import Knowledge
from research_memory.storage import Conflict, atomic, file_hash, read_json


def note(event_id, note_id="idea-a"):
    return {"id": note_id, "type": "idea", "title": "Candidate with conditions", "workstream_id": "system-development",
            "authors": ["user"], "conditions": ["condition A"], "sources": [{"event_id": event_id, "quote": "Only under condition A"}],
            "body": "A possible alternative, not an established finding.", "human_review": "accepted", "evidence_status": "unassessed"}


def test_review_is_independent_of_evidence_and_no_three_node_limit(store, event):
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    result = knowledge.commit({"processor": "fixture-v1", "event_ids": [event_id], "notes": [note(event_id, f"idea-{i}") for i in range(7)]})
    assert len(result["notes"]) == 7
    assert all(n["human_review"] == "accepted" and n["evidence_status"] == "unassessed" for n in result["notes"])
    assert store.status()["pending"] == 0


def test_bad_quote_and_unsupported_relation_not_acknowledged(store, event):
    event_id = store.capture(event)
    n = note(event_id)
    n["sources"][0]["quote"] = "invented quote"
    with pytest.raises(ValueError):
        Knowledge(store).commit({"processor": "fixture", "event_ids": [event_id], "notes": [n]})
    assert store.status()["pending"] == 1
    n = note(event_id)
    n["relations"] = [{"type": "supports", "target": "idea-b"}]
    with pytest.raises(ValueError):
        Knowledge(store).save(n)


def test_human_edit_preserved_and_requires_hash_review(store, event):
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    value = knowledge.save(note(event_id))
    path = knowledge.vault / value["path"]
    atomic(path, path.read_bytes() + b"\nHuman correction\n")
    with pytest.raises(Conflict):
        knowledge.save(note(event_id), expected_version=1)
    assert "Human correction" in path.read_text()
    assert list((store.data / "conflicts").glob("*.json"))
    accepted = knowledge.accept_human_edit("idea-a", file_hash(path))
    assert accepted["needs_semantic_reconciliation"]


def test_canvas_relations_and_sources_resolve(store, event):
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    a, b = note(event_id, "idea-a"), note(event_id, "question-a")
    b["type"] = "question"
    a["relations"] = [{"type": "derived_from", "target": "question-a", "basis": "same discussion"}]
    knowledge.commit({"processor": "fixture", "event_ids": [event_id], "notes": [a, b]})
    graph = read_json(knowledge.graph("question-a")["path"])
    assert len(graph["nodes"]) == 2 and len(graph["edges"]) == 1
    assert all((knowledge.vault / n["file"]).is_file() for n in graph["nodes"])
    assert (knowledge.vault / "Sources" / (event_id + ".md")).is_file()


def test_verified_evidence_requires_actual_retrieval(store, event):
    event_id = store.capture(event)
    n = note(event_id)
    n["type"] = "evidence"
    n["evidence"] = {"url": "https://example.org/paper", "locator": "abstract", "excerpt": "claim", "access_level": "abstract_only", "verification": "verified"}
    with pytest.raises(ValueError):
        Knowledge(store).save(n)
