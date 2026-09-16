"""Hash-checked view migration with durable before/after images and guarded rollback."""
from copy import deepcopy
import json
from pathlib import Path
import uuid
import yaml

from .storage import Conflict, atomic, digest, encode, file_hash, now, read_json, write_json
from .readability import ViewPaths, render_source, rewrite_links, source_title


class ReadabilityMigration:
    def __init__(self, knowledge):
        self.knowledge = knowledge
        self.store = knowledge.store
        self.root = self.store.config.root
        self.vault = knowledge.vault

    def prepare(self):
        with self.store.lock("knowledge"), self.store.lock("source-views"):
            return self._prepare()

    def _prepare(self):
        identity = "readability_" + uuid.uuid4().hex
        folder = self.store.data / "migrations" / identity
        paths = ViewPaths(self.store)
        paths.value = deepcopy(paths.value)
        paths.value["enabled"] = True
        notes = self.knowledge.records()
        operations, changes = {}, []

        def stage(path, content):
            path = self.store.config.inside(path)
            relative = path.relative_to(self.root).as_posix()
            before = path.read_bytes() if path.exists() else None
            if before == content:
                return
            before_hash = digest(before) if before is not None else None
            after_hash = digest(content) if content is not None else None
            for data, code in ((before, before_hash), (content, after_hash)):
                if data is not None:
                    atomic(folder / "blobs" / code, data)
            if relative in operations and operations[relative]["after"] != after_hash:
                raise Conflict("Two proposed writes disagree: " + relative)
            operations[relative] = {"path": relative, "before": before_hash, "after": after_hash}

        for note in sorted(notes, key=lambda n: n["id"]):
            old = paths.validate(note["path"])
            if not (self.vault / old).is_file() or file_hash(self.vault / old) != note["published_hash"] or note.get("needs_semantic_reconciliation"):
                raise Conflict("Review the human-edited/missing note before migration: " + old)
            new = paths.allocate("note", note["id"], note["title"])
            if old != new:
                paths.value["aliases"][old] = new
            changes.append({"kind": "note", "id": note["id"], "old": old, "new": new, "title": note["title"]})

        source_ids = {s["event_id"] for n in notes for s in n["sources"]}
        source_ids |= {event_id for n in notes for rel in n.get("relations", []) for event_id in rel.get("source_event_ids", [])}
        source_ids |= {p.stem for p in (self.vault / "Sources").glob("ev_*.md") if (self.store.events / (p.stem + ".json")).is_file()}
        for event_id in sorted(source_ids):
            envelope = self.store.get(event_id)
            old_paths = ViewPaths(self.store)
            old = old_paths.source(event_id)
            new = paths.source(event_id)
            title = source_title(envelope)
            prior = read_json(self.store.data / "source-views" / (event_id + ".json"), {})
            existing = self.vault / old
            permalink = None
            if existing.exists():
                content = existing.read_text(encoding="utf-8")
                parts = content.split("---", 2) if content.startswith("---\n") else []
                metadata = yaml.safe_load(parts[1]) if len(parts) == 3 else {}
                permalink = metadata.get("permalink") if isinstance(metadata, dict) else None
                if prior:
                    untouched = file_hash(existing) == prior["published_hash"]
                else:
                    # Basic Memory may add its permalink and remove the final newline.
                    # Only that known index annotation is accepted; all source prose must match.
                    header = {"title": event_id, "type": "source", "tags": ["raw-source"], "event_id": event_id, "canonical_sha256": envelope["content_hash"]}
                    body = "\n\n````json\n" + json.dumps(envelope, ensure_ascii=False, indent=2) + "\n````"
                    normalized = {k: v for k, v in metadata.items() if k != "permalink"} if isinstance(metadata, dict) else {}
                    untouched = len(parts) == 3 and normalized == header and parts[2].rstrip("\n") == body and (permalink is None or isinstance(permalink, str) and bool(permalink.strip()))
                if not untouched:
                    raise Conflict("Human-edited source view requires review: " + old)
            text, attachments = render_source(self.store, envelope, new, title, permalink=permalink)
            if old != new:
                paths.value["aliases"][old] = new
                stage(existing, None)
            stage(self.vault / new, text.encode("utf-8"))
            for relative, data in attachments:
                stage(self.vault / relative, data)
            stage(self.store.data / "source-views" / (event_id + ".json"), encode({"path": new, "title": title, "published_hash": digest(text.encode("utf-8"))}))
            changes.append({"kind": "source", "id": event_id, "old": old, "new": new, "title": title})

        for note in notes:
            value = deepcopy(note)
            value["path"] = paths.note(note["id"])
            value["view_revision"] = identity
            text = self.knowledge.render(value, paths)
            value["published_hash"] = digest(text.encode("utf-8"))
            if note["path"].replace("\\", "/") != value["path"]:
                stage(self.vault / note["path"], None)
            stage(self.vault / value["path"], text.encode("utf-8"))
            stage(self.store.data / "notes" / (note["id"] + ".json"), encode(value))

        # Existing user-authored Canvas layout and navigation content retain their geometry/prose.
        def update(value):
            if isinstance(value, dict):
                return {key: update(val) for key, val in value.items()}
            if isinstance(value, list):
                return [update(v) for v in value]
            if isinstance(value, str):
                return paths.value["aliases"].get(value, rewrite_links(value, paths.value["aliases"]))
            return value

        managed = {c[side] for c in changes for side in ("old", "new")}
        for p in self.vault.rglob("*"):
            relative = p.relative_to(self.vault)
            if any(part.startswith(".") for part in relative.parts) or relative.parts[0] in {"System", "projects", "Attachments"}:
                continue
            if relative.as_posix() in managed or not p.is_file():
                continue
            if p.suffix == ".md" and relative.parts[0] != "Sources":
                before = p.read_text(encoding="utf-8")
                after = rewrite_links(before, paths.value["aliases"])
                if after != before:
                    stage(p, after.encode("utf-8"))
            elif p.suffix == ".canvas":
                value = read_json(p)
                changed = update(value)
                if changed != value:
                    stage(p, encode(changed))
            elif p.suffix == ".base":
                before = p.read_text(encoding="utf-8")
                value = yaml.safe_load(before)
                changed = update(value)
                if changed != value:
                    stage(p, yaml.safe_dump(changed, allow_unicode=True, sort_keys=False).encode("utf-8"))
        stage(paths.file, encode(paths.value))
        plan = {"id": identity, "project_id": self.store.config.project_id, "state": "prepared", "at": now(),
                "changes": changes, "operations": list(operations.values()), "canonical_events_modified": False}
        write_json(folder / "plan.json", plan)
        return {"plan": str((folder / "plan.json").relative_to(self.root)), "changes": changes, "files": len(operations), "state": "prepared"}

    def load(self, path):
        path = self.store.config.inside(path)
        if not path.is_relative_to(self.store.data / "migrations") or path.name != "plan.json":
            raise ValueError("Expected a local migration plan")
        plan = read_json(path)
        if plan["project_id"] != self.store.config.project_id:
            raise ValueError("Wrong migration project")
        for op in plan["operations"]:
            target = self.store.config.inside(op["path"])
            allowed = target.is_relative_to(self.vault) and not any(p.startswith(".") for p in target.relative_to(self.vault).parts)
            allowed |= target.is_relative_to(self.store.data / "notes") or target.is_relative_to(self.store.data / "source-views") or target == self.store.data / "view-paths.json"
            if not allowed:
                raise ValueError("Migration write outside the view/catalog scope")
            for field in ("before", "after"):
                code = op[field]
                if code and (len(code) != 64 or any(c not in "0123456789abcdef" for c in code) or file_hash(path.parent / "blobs" / code) != code):
                    raise ValueError("Migration blob hash mismatch")
        return path, plan

    def apply(self, path, rollback=False):
        with self.store.lock("knowledge"), self.store.lock("source-views"):
            path, plan = self.load(path)
            expected_states = {"applied", "unknown", "applying", "rolling_back"} if rollback else {"prepared"}
            if plan["state"] not in expected_states:
                raise Conflict("Inspect the migration state before applying or rolling back: " + plan["state"])
            for op in plan["operations"]:
                target = self.store.config.inside(op["path"])
                actual = file_hash(target) if target.exists() else None
                accepted = {op["after"], op["before"]} if rollback else {op["before"]}
                if actual not in accepted:
                    raise Conflict("File changed since migration planning; preserved: " + op["path"])
            field = "before" if rollback else "after"
            plan["state"] = "rolling_back" if rollback else "applying"
            write_json(path, plan)
            try:
                # Publish targets before removing former paths; only checked in-root files are removed.
                for op in sorted(plan["operations"], key=lambda op: op[field] is None):
                    target = self.store.config.inside(op["path"])
                    if op[field] is None:
                        target.unlink(missing_ok=True)
                    else:
                        atomic(target, (path.parent / "blobs" / op[field]).read_bytes())
                plan["state"] = "rolled_back" if rollback else "applied"
            except Exception:
                plan["state"] = "unknown"
                write_json(path, plan)
                raise
            plan["completed_at"] = now()
            write_json(path, plan)
        # Disposable projection; do not regenerate a user's Canvas or overwrite navigation during rollback.
        from .graph_view import publish_projection
        graph = publish_projection(self.knowledge)
        return {"state": plan["state"], "plan": str(path.relative_to(self.root)), "graph": graph}
