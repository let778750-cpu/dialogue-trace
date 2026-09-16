from __future__ import annotations

import json
import html
from pathlib import Path
import uuid
import yaml
from .storage import Store, Conflict, now, atomic, read_json, write_json, file_hash, safe_id, digest, encode
from .readability import ViewPaths, TYPE_LABELS, RELATION_LABELS, REVIEW_LABELS, EVIDENCE_LABELS, wiki, source_title, render_source, rewrite_links


TYPES = {"question", "idea", "evidence", "experiment", "task", "decision"}
RELATIONS = set(RELATION_LABELS)


def text_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from text_values(v)
    elif isinstance(value, list):
        for v in value:
            yield from text_values(v)


class Knowledge:
    def __init__(self, store: Store):
        self.store = store
        self.vault = store.config.directory("vault")

    def records(self, workstream=None, project=None):
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        result = []
        for path in (self.store.data / "notes").glob("*.json"):
            note = read_json(path)
            if (workstream is None or note["workstream_id"] == workstream) and (project is None or projects.note_project(note) == project):
                result.append(note)
        return result

    def validate(self, note):
        for key in ("id", "type", "title", "workstream_id", "authors", "conditions", "sources", "body"):
            if key not in note:
                raise ValueError(f"Missing note field: {key}")
        safe_id(note["id"])
        safe_id(note["workstream_id"])
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        if projects.active:
            project = projects.context(note.get("research_project_id"), note["workstream_id"])
            note["research_project_id"] = project
            old = read_json(self.store.data / "notes" / (note["id"] + ".json"))
            if old and projects.note_project(old) != project:
                raise Conflict("Note ID belongs to another research project; create a distinct ID")
        if note["type"] not in TYPES:
            raise ValueError("Invalid research note type")
        if not note["authors"] or not note["sources"]:
            raise ValueError("Authors and source references are mandatory")
        for key in ("authors", "conditions", "sources"):
            if not isinstance(note[key], list):
                raise ValueError(f"{key} must be a list")
        if note.get("human_review", "unreviewed") not in {"unreviewed", "accepted", "rejected", "needs_revision"}:
            raise ValueError("Invalid human review status")
        if note.get("evidence_status", "unassessed") not in {"unassessed", "unsupported", "supported", "mixed", "contradicted"}:
            raise ValueError("Invalid evidence status")
        for source in note["sources"]:
            event = self.store.get(source["event_id"])["event"]
            text = json.dumps(event["payload"], ensure_ascii=False)
            if source.get("quote") and source["quote"] not in text:
                # Match decoded text, rather than JSON escaping of newlines and quotes.
                if not any(source["quote"] in s for s in text_values(event["payload"])):
                    raise ValueError("Source quotation is not present in its event")
        for relation in note.get("relations", []):
            if relation["type"] not in RELATIONS:
                raise ValueError("Invalid relation")
            safe_id(relation["target"])
            if relation["type"] in {"adopts", "rejects"} and note["type"] != "decision":
                raise ValueError("Adoption/rejection must originate from a decision record")
            if relation["type"] in {"supports", "contradicts", "adopts", "rejects"} and not relation.get("basis"):
                raise ValueError("Support/contradiction requires evidence basis")
            if relation["type"] in {"supports", "contradicts", "adopts", "rejects"}:
                if not relation.get("source_event_ids"):
                    raise ValueError("Support/contradiction requires provenance event IDs")
                for event_id in relation["source_event_ids"]:
                    self.store.get(event_id)
        if note["type"] == "evidence":
            evidence = note.get("evidence", {})
            for key in ("url", "locator", "excerpt", "access_level", "verification"):
                if not evidence.get(key):
                    raise ValueError(f"Evidence requires {key}")
            if evidence["access_level"] not in {"full_text", "abstract_only", "metadata_only", "local_artifact"}:
                raise ValueError("Invalid evidence access level")
            if evidence["verification"] not in {"unverified", "verified"}:
                raise ValueError("Invalid verification status")
            if evidence["verification"] == "verified" and not evidence.get("checked_source_event"):
                raise ValueError("Verified evidence requires a source retrieval event")
            if evidence.get("checked_source_event"):
                checked = self.store.get(evidence["checked_source_event"])["event"]
                if checked["kind"] not in {"source", "tool_result"}:
                    raise ValueError("Evidence verification must reference retrieved source content")
                if not any(evidence["excerpt"] in text for text in text_values(checked["payload"])):
                    raise ValueError("Evidence excerpt is absent from the retrieved source")
        return note

    def save(self, note, expected_version=0):
        self.validate(note)
        note_id = note["id"]
        record_path = self.store.data / "notes" / (note_id + ".json")
        with self.store.lock("knowledge"):
            old = read_json(record_path)
            paths = ViewPaths(self.store)
            path = self.vault / paths.note(note_id, note["title"], old or note)
            version = old["version"] if old else 0
            if version != expected_version:
                raise Conflict(f"Note version is {version}; expected {expected_version}")
            if path.exists() and (not old or file_hash(path) != old["published_hash"]):
                conflict = self.store.data / "conflicts" / (note_id + "-" + uuid.uuid4().hex + ".json")
                write_json(conflict, {"proposed": note, "expected_version": expected_version,
                                      "disk_hash": file_hash(path), "at": now()})
                raise Conflict(f"Human edit detected. Proposed revision saved: {conflict}")
            value = dict(note, version=version + 1, updated_at=now(),
                         human_review=note.get("human_review", "unreviewed"), evidence_status=note.get("evidence_status", "unassessed"))
            text = self.render(value, paths)
            value["published_hash"] = digest(text.encode("utf-8"))
            value["path"] = path.relative_to(self.vault).as_posix()
            # Keep a write-ahead revision. A crash between note and catalog publication produces an explicit conflict.
            write_json(self.store.data / "revisions" / note_id / f"{value['version']}.json", value)
            atomic(path, text.encode("utf-8"))
            write_json(record_path, value)
            paths.save()
            for source in note["sources"]:
                self.source_view(source["event_id"])
        return value

    def render(self, note, paths=None):
        paths = paths or ViewPaths(self.store)
        if paths.value.get("schema_version", 1) >= 2:
            from .presentation import render_note
            return render_note(self, note, paths)
        known = {n["id"]: n for n in self.records()}
        known.update(getattr(self, "batch_records", {}))
        known[note["id"]] = note
        metadata = {k: note[k] for k in ("id", "title", "workstream_id", "version", "updated_at", "human_review", "evidence_status")}
        metadata.update(type=note["type"], permalink="notes/" + note["id"], tags=["research", note["type"]],
                        authors=note["authors"], conditions=note["conditions"], source_event_ids=[s["event_id"] for s in note["sources"]],
                        cssclasses=["research-note"], aliases=list(dict.fromkeys([note["id"], *note.get("aliases", [])])))
        state = f"{TYPE_LABELS[note['type']]} · 人工审阅：{REVIEW_LABELS[note['human_review']]} · 证据：{EVIDENCE_LABELS[note['evidence_status']]}"
        parts = ["---", yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip(), "---", "", "# " + note["title"], "", state, "", rewrite_links(note["body"], paths.value["aliases"]), "", "## 适用条件"]
        for condition in note["conditions"]:
            parts.append("- [condition] " + condition)
        parts.extend(["", "## 原话与来源"])
        for source in note["sources"]:
            link = wiki(paths.source(source["event_id"]), source_title(self.store.get(source["event_id"])))
            parts.append(f"- {link}: {source.get('quote', source.get('locator', '公开记录'))}")
        if evidence := note.get("evidence"):
            parts.extend(["", "## 证据记录", "```json", json.dumps(evidence, ensure_ascii=False, indent=2), "```"])
        parts.extend(["", "## 关联关系"])
        for relation in note.get("relations", []):
            target = known.get(relation["target"], {"title": relation["target"]})
            path = paths.note(relation["target"], target["title"], target)
            parts.append(f"- {relation['type']} {wiki(path, target['title'])} ({relation.get('basis', '')})")
        audit = f"稳定标识：{note['id']}\n提出者：{'、'.join(note['authors'])}\n修订：{note['version']} · {note['updated_at']}"
        # A contiguous HTML block keeps Obsidian's Markdown parser from lifting prose outside details.
        parts.extend(["", "<details><summary>溯源与修订信息</summary><pre>" + html.escape(audit) + "</pre></details>"])
        return "\n".join(parts) + "\n"

    def source_view(self, event_id):
        envelope = self.store.get(event_id)
        with self.store.lock("source-views"):
            paths = ViewPaths(self.store)
            relative = paths.source(event_id)
            path = self.vault / relative
            if path.exists():
                return relative
            title = source_title(envelope)
            value, attachments = render_source(self.store, envelope, relative, title)
            for name, content in attachments:
                atomic(self.vault / name, content)
            atomic(path, value.encode("utf-8"))
            paths.save()
            write_json(self.store.data / "source-views" / (event_id + ".json"), {"path": relative, "published_hash": file_hash(path), "title": title})
            return relative

    def commit(self, batch):
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        if projects.active and batch.get('research_project_id'):
            project = projects.get(batch['research_project_id'])['id']
            if any(projects.note_project(n) != project for n in batch.get('notes', [])):
                raise Conflict('Publication contains a note owned by another project')
        ids = batch["event_ids"]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate event IDs in batch")
        for event_id in ids:
            self.store.get(event_id)
        notes = batch.get("notes", [])
        for note in notes:
            self.validate(note)
            if not any(source["event_id"] in ids for source in note["sources"]):
                raise ValueError("Each extracted note must cite the processed event range")
        known = {n["id"] for n in self.records()} | {n["id"] for n in notes}
        for note in notes:
            for relation in note.get("relations", []):
                if relation["target"] not in known:
                    raise ValueError("Unresolved relationship target")
        self.batch_records = {n["id"]: n for n in notes}
        try:
            saved = [self.save(note, note.pop("expected_version", 0)) for note in notes]
        finally:
            self.batch_records = {}
        receipt = self.store.acknowledge(ids, batch["processor"], [n["id"] for n in saved], batch.get("no_candidate_reason"))
        self.views()
        return {"receipt": receipt, "notes": saved}

    def accept_human_edit(self, note_id, expected_disk_hash):
        record_path = self.store.data / "notes" / (safe_id(note_id) + ".json")
        record = read_json(record_path)
        path = self.vault / ViewPaths(self.store).note(note_id, record=record)
        with self.store.lock("knowledge"):
            if file_hash(path) != expected_disk_hash:
                raise Conflict("File changed again during review")
            record = read_json(record_path)
            # Preserve the human's complete text as a revision; do not guess semantic state from prose edits.
            record.update(published_hash=expected_disk_hash, version=record["version"] + 1, human_edit_at=now(), needs_semantic_reconciliation=True)
            atomic(self.store.data / "revisions" / note_id / f"human-{record['version']}.md", path.read_bytes())
            write_json(record_path, record)
            return record

    def views(self, project=None):
        from .research_projects import ResearchProjects
        if ResearchProjects(self.store.config).active:
            from .presentation import views
            with self.store.lock('navigation-views'):
                return views(self, project)
        notes = sorted(self.records(), key=lambda n: (n["type"], n["title"]))
        paths = ViewPaths(self.store)
        sections = ["# 科研记忆", "", "![[Research.base]]", ""]
        for kind in sorted(TYPES):
            sections.extend(["## " + TYPE_LABELS[kind], ""])
            sections += [f"- {wiki(paths.note(n['id'], n['title'], n), n['title'])} ({REVIEW_LABELS[n['human_review']]}；{EVIDENCE_LABELS[n['evidence_status']]})" for n in notes if n["type"] == kind]
            sections.append("")
        from .runs import Runs
        sections.extend(["## 实验运行", ""])
        sections += [f"- `{r['run_id']}`: {r['status']}" for r in Runs(self.store).reconcile()]
        atomic(self.vault / "Research.md", "\n".join(sections).encode("utf-8"))
        base = {"filters": {"and": ['file.inFolder("Notes")']}, "views": [
            {"type": "table", "name": "科研记录", "order": ["title", "type", "human_review", "evidence_status"]}]}
        atomic(self.vault / "Research.base", yaml.safe_dump(base, sort_keys=False).encode("utf-8"))
        from .graph_view import publish_projection
        graph = publish_projection(self)
        return {"notes": len(notes), "home": str(self.vault / "Research.md"), "graph": graph}

    def graph(self, focus, depth=1, cross_project=False):
        records = {n["id"]: n for n in self.records()}
        if focus not in records:
            raise ValueError("Unknown focus note")
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        if projects.active and not cross_project:
            owner = projects.note_project(records[focus])
            records = {k: n for k, n in records.items() if projects.note_project(n) == owner}
        selected = {focus}
        for _ in range(min(depth, 3)):
            expanded = set(selected)
            for n in records.values():
                for relation in n.get("relations", []):
                    if n["id"] in selected or relation["target"] in selected:
                        expanded.update([n["id"], relation["target"]])
            selected = expanded
        selected &= records.keys()
        distances = {focus: 0}
        for _ in range(len(selected)):
            for key in sorted(selected):
                for relation in records[key].get("relations", []):
                    target = relation["target"]
                    if target in selected:
                        if key in distances and target not in distances:
                            distances[target] = distances[key] + 1
                        if target in distances and key not in distances:
                            distances[key] = distances[target] + 1
        layers = {}
        for key in sorted(selected):
            layers.setdefault(distances.get(key, 0), []).append(key)
        nodes = []
        for distance, keys in sorted(layers.items()):
            for i, key in enumerate(keys):
                nodes.append({"id": key, "type": "file", "file": records[key]["path"].replace("\\", "/"),
                              "subpath": "#" + records[key]["title"], "x": -distance * 700,
                              "y": int((i - (len(keys) - 1) / 2) * 390), "width": 460, "height": 280})
        positions = {n["id"]: n for n in nodes}
        labels = RELATION_LABELS
        edges = []
        for key in sorted(selected):
            for relation in records[key].get("relations", []):
                if relation["target"] in selected:
                    source_pos, target_pos = positions[key], positions[relation["target"]]
                    if source_pos["x"] == target_pos["x"]:
                        source_side, target_side = ("bottom", "top") if source_pos["y"] < target_pos["y"] else ("top", "bottom")
                    else:
                        source_side, target_side = ("right", "left") if source_pos["x"] < target_pos["x"] else ("left", "right")
                    edges.append({"id": "edge_" + str(len(edges)), "fromNode": key, "toNode": relation["target"],
                                  "fromSide": source_side, "toSide": target_side, "label": labels[relation["type"]], "toEnd": "none" if relation["type"] == "related_to" else "arrow"})
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        if projects.active:
            from .readability import clean_name
            path = projects.folder(projects.note_project(records[focus])) / "图谱" / (clean_name(records[focus]["title"], 60) + "关系图.canvas")
        else:
            path = self.vault / "Graphs" / (safe_id(focus) + ".canvas")
        # Regeneration retains user geometry for surviving stable nodes.
        old = read_json(path, {})
        positions = {n['id']: n for n in old.get('nodes', [])}
        for node in nodes:
            previous = positions.get(node['id'], {})
            node.update({k: previous[k] for k in ('x', 'y', 'width', 'height', 'color') if k in previous})
        write_json(path, {**old, "nodes": nodes, "edges": edges})
        return {"path": str(path), "nodes": len(nodes), "edges": len(edges)}
