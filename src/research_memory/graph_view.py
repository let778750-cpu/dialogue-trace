"""Rebuildable graph projection; canonical notes and events retain their authority."""
from collections import Counter
from copy import deepcopy
from pathlib import Path

from .storage import digest, encode, file_hash, now, write_json
from .readability import ViewPaths, source_title


def build_projection(knowledge):
    paths = ViewPaths(knowledge.store)
    projects = paths.projects
    nodes = []
    notes = sorted(knowledge.records(), key=lambda n: n["id"])
    known = {n["id"] for n in notes}
    edges = []
    issues = []
    for note in notes:
        # Older Windows records use backslashes; Obsidian's API always expects '/'.
        path = (knowledge.vault / note["path"].replace("\\", "/")).resolve()
        if not path.is_relative_to(knowledge.vault.resolve()):
            raise ValueError("Graph note path escapes vault")
        current_hash = file_hash(path) if path.is_file() else None
        dirty = current_hash != note["published_hash"] or note.get("needs_semantic_reconciliation", False)
        sources = []
        for source in note["sources"]:
            envelope = knowledge.store.get(source["event_id"])
            sources.append(dict(source, path=knowledge.source_view(source["event_id"]), title=source_title(envelope),
                                event_hash=envelope["content_hash"], author=envelope["event"].get("author"),
                                occurred_at=envelope["event"].get("occurred_at"),
                                captured_at=envelope.get("captured_at"),
                                session_id=envelope["event"].get("session_id"),
                                source=envelope["event"].get("source"),
                                source_sequence=envelope["event"].get("source_sequence"),
                                predecessors=envelope["event"].get("predecessors", [])))
        node = {key: deepcopy(note.get(key)) for key in (
            "id", "type", "title", "body", "workstream_id", "version", "updated_at", "authors",
            "conditions", "human_review", "evidence_status", "evidence", "run_id", "run_ids")}
        node.update(path=path.relative_to(knowledge.vault.resolve()).as_posix(), sources=sources, published_hash=note["published_hash"],
                    needs_reconciliation=bool(dirty), file_exists=path.is_file())
        if projects.active:
            from .presentation import display, run_cache
            node.update(research_project_id=projects.note_project(note), display=display(note, projects, run_cache(knowledge)))
        nodes.append(node)
        duplicates = Counter()
        for relation in note.get("relations", []):
            if relation["target"] not in known:
                issues.append({"source": note["id"], "target": relation["target"], "reason": "missing_target"})
                continue
            # Preserve same endpoints/type with different conditions, and even exact repeated assertions.
            identity = digest(encode({"source": note["id"], "relation": relation}))[:32]
            duplicates[identity] += 1
            edge = deepcopy(relation)
            edge.update(id=f"rel_{identity}_{duplicates[identity]}", source=note["id"], target=relation["target"],
                        source_version=note["version"], note_path=node["path"],
                        needs_reconciliation=bool(dirty))
            explicit = relation.get("source_event_ids", [])
            edge["provenance_scope"] = "relation" if explicit else "note"
            edge["sources"] = [dict(s) for s in sources if not explicit or s["event_id"] in explicit]
            for event_id in explicit:
                if not any(s["event_id"] == event_id for s in edge["sources"]):
                    envelope = knowledge.store.get(event_id)
                    edge["sources"].append({"event_id": event_id, "path": knowledge.source_view(event_id), "title": source_title(envelope),
                                             "event_hash": envelope["content_hash"]})
                    knowledge.source_view(event_id)
            edges.append(edge)
    graph = {"schema_version": 1, "project_id": knowledge.store.config.project_id, "path_aliases": paths.value["aliases"],
             "nodes": nodes, "edges": edges, "issues": issues}
    if projects.active:
        graph.update(schema_version=2, default_project_id=projects.default, projects=projects.records(examples=True),
                     branches=[{'id': w, 'project': p, 'name': projects.branch_name(w)} for w, p in projects.value['branches'].items()])
    graph['navigation'] = {'schema_version': 1, 'projects': {
        p['id']: {'entry_ids': p.get('graph_entry_ids', []), 'branches': p.get('graph_branch_entries', {})}
        for p in projects.records(examples=True)}}
    graph["revision"] = digest(encode(graph))
    graph["generated_at"] = now()
    return graph


def publish_projection(knowledge):
    # A graph rebuild must not race a new note publication and replace it with an older view.
    with knowledge.store.lock("knowledge"):
        graph = build_projection(knowledge)
        from .research_projects import ResearchProjects, SYSTEM
        path = knowledge.vault / ((SYSTEM if ResearchProjects(knowledge.store.config).active else 'System') + '/research-graph.json')
        write_json(path, graph)
    from .timeline import refresh_if_present
    refresh_if_present(knowledge.store)
    return {"path": str(path), "revision": graph["revision"], "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]), "issues": graph["issues"]}
