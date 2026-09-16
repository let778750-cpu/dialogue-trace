import base64
from copy import deepcopy
import json
import pytest

from research_memory.storage import Conflict, atomic, file_hash, read_json, write_json
from research_memory.knowledge import Knowledge
from research_memory.migration import ReadabilityMigration
from research_memory.readability import ViewPaths, clean_name, rewrite_links
from research_memory.obsidian import Obsidian
from test_knowledge import note


def setup_pair(store, event):
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    a, b = note(event_id), note(event_id, "question-a")
    a["title"], b["title"], b["type"] = "保留完整公开原文", "科研记忆的连续性", "question"
    a["relations"] = [{"type": "refines", "target": b["id"], "basis": "保留完整条件"}]
    knowledge.commit({"processor": "fixture", "event_ids": [event_id], "notes": [a, b]})
    return knowledge, event_id


def test_migration_preserves_identity_sources_canvas_and_can_rollback(store, event):
    knowledge, event_id = setup_pair(store, event)
    original_records = {n["id"]: deepcopy(n) for n in knowledge.records()}
    originals = {p: p.read_bytes() for p in knowledge.vault.rglob("*.md")}
    raw_hash = file_hash(store.events / (event_id + ".json"))
    canvas_path = knowledge.vault / "Graphs/manual.canvas"
    canvas = {"nodes": [{"id": "user-layout", "type": "file", "file": "Notes/idea-a.md", "x": 723, "y": -221, "width": 800, "height": 320}], "edges": []}
    write_json(canvas_path, canvas)
    migration = ReadabilityMigration(knowledge)
    prepared = migration.prepare()
    assert not ViewPaths(store).value["enabled"]
    migration.apply(prepared["plan"])
    record = next(n for n in knowledge.records() if n["id"] == "idea-a")
    assert record["path"] == "Notes/保留完整公开原文.md"
    assert not (knowledge.vault / "Notes/idea-a.md").exists()
    for n in knowledge.records():
        for key in ("id", "version", "authors", "conditions", "sources", "relations", "human_review", "evidence_status"):
            assert n.get(key) == original_records[n["id"]].get(key)
    assert file_hash(store.events / (event_id + ".json")) == raw_hash
    updated_canvas = read_json(canvas_path)
    assert updated_canvas["nodes"][0]["file"] == record["path"]
    assert updated_canvas["nodes"][0]["x"] == 723 and updated_canvas["nodes"][0]["width"] == 800
    assert Obsidian(store.config).path("Notes/idea-a.md") == record["path"]
    text = (knowledge.vault / record["path"]).read_text(encoding="utf-8")
    assert "[[Notes/科研记忆的连续性|科研记忆的连续性]]" in text
    assert not ViewPaths(store).source(event_id).endswith(event_id + ".md")
    migration.apply(prepared["plan"], rollback=True)
    assert {n["id"]: n for n in knowledge.records()} == original_records
    assert all(p.read_bytes() == content for p, content in originals.items())
    assert read_json(canvas_path) == canvas


def test_planned_migration_refuses_a_concurrent_human_change(store, event):
    knowledge, _ = setup_pair(store, event)
    migration = ReadabilityMigration(knowledge)
    prepared = migration.prepare()
    path = knowledge.vault / "Notes/idea-a.md"
    human = path.read_bytes() + b"\nUser changes after preview\n"
    atomic(path, human)
    with pytest.raises(Conflict):
        migration.apply(prepared["plan"])
    assert path.read_bytes() == human
    assert not ViewPaths(store).value["enabled"]


def test_rollback_refuses_to_erase_later_human_edits(store, event):
    knowledge, _ = setup_pair(store, event)
    migration = ReadabilityMigration(knowledge)
    prepared = migration.prepare()
    migration.apply(prepared["plan"])
    path = knowledge.vault / ViewPaths(store).note("idea-a")
    atomic(path, path.read_bytes() + b"\nLater review\n")
    with pytest.raises(Conflict):
        migration.apply(prepared["plan"], rollback=True)
    assert "Later review" in path.read_text(encoding="utf-8")


def test_unknown_partial_migration_is_not_automatically_replayed_and_can_restore(store, event, monkeypatch):
    knowledge, _ = setup_pair(store, event)
    migration = ReadabilityMigration(knowledge)
    prepared = migration.prepare()
    import research_memory.migration as module
    real = module.atomic
    count = 0
    def interrupted(path, content):
        nonlocal count
        count += 1
        if count == 3:
            raise OSError("simulated interrupted publication")
        return real(path, content)
    monkeypatch.setattr(module, "atomic", interrupted)
    with pytest.raises(OSError):
        migration.apply(prepared["plan"])
    assert read_json(store.config.root / prepared["plan"])["state"] == "unknown"
    with pytest.raises(Conflict):
        migration.apply(prepared["plan"])
    monkeypatch.setattr(module, "atomic", real)
    migration.apply(prepared["plan"], rollback=True)
    assert (knowledge.vault / "Notes/idea-a.md").is_file()


def test_new_notes_with_duplicate_titles_keep_different_ids_and_paths(store, event):
    knowledge, event_id = setup_pair(store, event)
    migration = ReadabilityMigration(knowledge)
    migration.apply(migration.prepare()["plan"])
    a, b = note(event_id, "idea-new-1"), note(event_id, "idea-new-2")
    a["title"] = b["title"] = "同名方案"
    a["relations"] = [{"type": "related_to", "target": b["id"]}]
    saved = knowledge.commit({"processor": "fixture-new", "event_ids": [event_id], "notes": [a, b]})["notes"]
    assert saved[0]["path"] != saved[1]["path"]
    assert all((knowledge.vault / n["path"]).is_file() for n in saved)
    text = (knowledge.vault / saved[0]["path"]).read_text(encoding="utf-8")
    assert saved[1]["path"].removesuffix(".md") + "|同名方案" in text
    changed = dict(a, title="换个标题")
    assert knowledge.save(changed, expected_version=1)["path"] == saved[0]["path"]


def test_source_view_keeps_all_public_text_and_embeds_image_without_base64_prose(store, event):
    image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jNhoAAAAASUVORK5CYII=")
    event["payload"] = {"content": [{"type": "input_text", "text": "第一段完整公开文本\n\n仍然保留。"}, {"type": "input_image", "reference": "data:image/png;base64," + base64.b64encode(image).decode()}, {"type": "input_text", "text": "图片后的第二段，也要完整保存。"}]}
    event_id = store.capture(event)
    knowledge = Knowledge(store)
    path = knowledge.vault / knowledge.source_view(event_id)
    text = path.read_text(encoding="utf-8")
    assert "第一段完整公开文本\n\n仍然保留。" in text and "图片后的第二段，也要完整保存。" in text
    assert "data:image/png;base64" not in text
    assert next((knowledge.vault / "Attachments").glob("*.png")).read_bytes() == image
    assert "data:image/png;base64" in json.dumps(store.get(event_id), ensure_ascii=False)


def test_adoption_requires_decision_provenance_without_changing_evidence(store, event):
    knowledge, event_id = setup_pair(store, event)
    decision = note(event_id, "decision-a")
    decision["relations"] = [{"type": "adopts", "target": "idea-a", "basis": "用户选择"}]
    with pytest.raises(ValueError):
        knowledge.save(decision)
    decision["type"] = "decision"
    with pytest.raises(ValueError):
        knowledge.save(decision)
    decision["relations"][0]["source_event_ids"] = [event_id]
    saved = knowledge.save(decision)
    assert saved["evidence_status"] == "unassessed"


def test_code_literals_are_not_renamed_and_windows_names_are_valid():
    aliases = {"Notes/old.md": "Notes/中文新名.md"}
    text = "[[Notes/old#段落|原来显示]]\n`[[Notes/old]]`\n```md\n[[Notes/old]]\n```\n"
    changed = rewrite_links(text, aliases)
    assert changed.startswith("[[Notes/中文新名#段落|原来显示]]")
    assert "`[[Notes/old]]`" in changed and "```md\n[[Notes/old]]" in changed
    assert clean_name("CON") == "记录-CON"
    assert clean_name('试验: A/B?') == '试验 A B'


def test_legacy_index_permalink_survives_migration_but_prose_edits_are_rejected(store, event):
    import yaml
    knowledge, event_id = setup_pair(store, event)
    envelope = store.get(event_id)
    header = {"title": event_id, "type": "source", "tags": ["raw-source"], "event_id": event_id, "canonical_sha256": envelope["content_hash"], "permalink": "original-project/sources/" + event_id.replace("_", "-")}
    content = "---\n" + yaml.safe_dump(header, sort_keys=False) + "---\n\n````json\n" + json.dumps(envelope, ensure_ascii=False, indent=2) + "\n````"
    path = knowledge.vault / ("Sources/" + event_id + ".md")
    atomic(path, (content + "\nHuman annotation").encode("utf-8"))
    (store.data / "source-views" / (event_id + ".json")).unlink()
    migration = ReadabilityMigration(knowledge)
    with pytest.raises(Conflict):
        migration.prepare()
    atomic(path, content.encode("utf-8"))
    migration.apply(migration.prepare()["plan"])
    new = knowledge.vault / ViewPaths(store).source(event_id)
    assert yaml.safe_load(new.read_text(encoding="utf-8").split("---", 2)[1])["permalink"] == header["permalink"]
