from copy import deepcopy
from research_memory.graph_view import build_projection, publish_projection
from research_memory.knowledge import Knowledge
from research_memory.storage import atomic, read_json, write_json, file_hash, Conflict
import pytest


def make_note(event_id, id="idea-a"):
    return {"id": id, "type": "idea", "title": "按需展开", "workstream_id": "system-development",
            "authors": ["user"], "conditions": ["条件 A"], "sources": [{"event_id": event_id}],
            "body": "候选方法", "human_review": "accepted", "evidence_status": "unassessed"}


def test_parallel_conditions_and_opposing_relations_survive(store, event):
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    target = make_note(event_id, "question-a")
    knowledge.save(target)
    note = make_note(event_id)
    note["relations"] = [
        {"type": "supports", "target": "question-a", "basis": "条件 A", "conditions": ["样本少"], "source_event_ids": [event_id]},
        {"type": "supports", "target": "question-a", "basis": "条件 B", "source_event_ids": [event_id]},
        {"type": "contradicts", "target": "question-a", "basis": "条件 C", "source_event_ids": [event_id]},
    ]
    knowledge.save(note)
    graph = build_projection(knowledge)
    assert len(graph["edges"]) == 3
    assert len({e["id"] for e in graph["edges"]}) == 3
    assert graph["edges"][0]["conditions"] == ["样本少"]
    assert all(e["sources"][0]["event_id"] == event_id for e in graph["edges"])
    assert all(e["provenance_scope"] == "relation" for e in graph["edges"])
    # Reordering assertions must not change relationship identity.
    note["relations"].reverse()
    knowledge.save(note, expected_version=1)
    assert {e["id"] for e in build_projection(knowledge)["edges"]} == {e["id"] for e in graph["edges"]}


def test_graph_rebuild_preserves_canvas_and_flags_human_edits(store, event):
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    saved = knowledge.save(make_note(event_id))
    canvas = knowledge.vault / "Graphs/manual.canvas"
    atomic(canvas, b'{"manual":true}')
    path = knowledge.vault / saved["path"]
    atomic(path, path.read_bytes() + "\n人工补充\n".encode())
    report = publish_projection(knowledge)
    graph = read_json(report["path"])
    assert graph["nodes"][0]["needs_reconciliation"]
    assert graph["nodes"][0]["human_review"] == "accepted"
    assert graph["nodes"][0]["evidence_status"] == "unassessed"
    assert canvas.read_bytes() == b'{"manual":true}'
    assert "人工补充" in path.read_text(encoding="utf-8")


def test_navigation_and_raw_files_are_not_research_entities(store, event):
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    n = make_note(event_id)
    knowledge.commit({"processor": "graph-test", "event_ids": [event_id], "notes": [n]})
    graph = read_json(knowledge.vault / "System/research-graph.json")
    assert [n["id"] for n in graph["nodes"]] == ["idea-a"]
    assert graph["nodes"][0]["sources"][0]["path"].startswith("Sources/")
    assert len(list(knowledge.vault.rglob("*.md"))) > 1


def test_duplicate_assertions_are_preserved_and_note_sources_not_mislabelled(store, event):
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    knowledge.save(make_note(event_id, "idea-b"))
    n = make_note(event_id)
    r = {"type": "refines", "target": "idea-b", "basis": "设计细化"}
    n["relations"] = [r, deepcopy(r)]
    knowledge.save(n)
    edges = build_projection(knowledge)["edges"]
    assert len(edges) == 2 and edges[0]["id"] != edges[1]["id"]
    assert all(e["provenance_scope"] == "note" for e in edges)


def test_legacy_windows_paths_open_in_obsidian_without_mutating_records(store, event, monkeypatch):
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    knowledge.save(make_note(event_id, "idea-b"))
    note = make_note(event_id)
    note["relations"] = [{"type": "refines", "target": "idea-b"}]
    knowledge.save(note)
    records = list(knowledge.records())
    for record in records:
        record["path"] = record["path"].replace("/", "\\")
    monkeypatch.setattr(knowledge, "records", lambda: records)
    graph = build_projection(knowledge)
    assert all(n["path"].startswith("Notes/") for n in graph["nodes"])
    assert all(not n["needs_reconciliation"] for n in graph["nodes"])
    assert graph["edges"][0]["note_path"] == "Notes/idea-a.md"
    assert all("\\" in r["path"] for r in records)


def test_graph_entries_are_versioned_project_metadata_and_do_not_modify_science(store, event):
    from research_memory.research_projects import ResearchProjects, initial_catalog
    k = Knowledge(store)
    id = store.capture(event)
    q = make_note(id, 'q'); q['type'] = 'question'
    note = k.save(q)
    catalog, ownership = initial_catalog(store.config, list(k.records()), [], [])
    write_json(store.data / 'research-projects.json', catalog)
    write_json(store.data / 'project-ownership.json', ownership)
    p = ResearchProjects(store.config)
    before = file_hash(k.vault / note['path'])
    result = p.set_graph_entries(p.default, ['q'], 1, 'system-development')
    assert result['version'] == 2
    assert file_hash(k.vault / note['path']) == before
    assert p.value['projects'][p.default]['graph_branch_entries']['system-development'] == ['q']
    with pytest.raises(Conflict):
        p.set_graph_entries(p.default, ['q'], 1)
    with pytest.raises(ValueError):
        p.set_graph_entries('sample-synthetic-noise', ['q'], 2)
    with pytest.raises(ValueError):
        p.set_graph_entries(p.default, ['missing'], 2)


def test_projection_preserves_event_occurrence_ingestion_and_causal_fields(store, event):
    event = dict(event, occurred_at='2026-01-01T00:00:00Z', source_sequence=7, predecessors=[])
    id = store.capture(event); k = Knowledge(store)
    k.save(make_note(id))
    source = build_projection(k)['nodes'][0]['sources'][0]
    assert source['occurred_at'] == event['occurred_at']
    assert source['captured_at'] == store.get(id)['captured_at']
    assert source['source_sequence'] == 7
    assert source['predecessors'] == []
    assert source['session_id'] == event['session_id']
