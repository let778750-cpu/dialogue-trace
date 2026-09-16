import pytest
from research_memory.projects import enabled, register, resolve, search_all
from research_memory.storage import write_json


def test_only_explicitly_enabled_projects_resolve(store):
    assert list(enabled(store.config)) == [store.config.project_id]
    write_json(store.data / "enabled-projects.json", {
        "additional": {"enabled": True, "path": "vault/projects/additional"},
        "disabled": {"enabled": False, "path": "vault/projects/disabled"}})
    assert resolve(store.config, "additional")[1] == store.config.directory("vault") / "projects/additional"
    with pytest.raises(ValueError, match="enabled"):
        resolve(store.config, "disabled")


def test_registry_paths_cannot_escape_unique_root(store):
    write_json(store.data / "enabled-projects.json", {"bad": {"enabled": True, "path": "../outside"}})
    with pytest.raises(ValueError, match="escapes"):
        enabled(store.config)


def test_secondary_notes_do_not_mark_primary_index_stale(store):
    write_json(store.data / "health/index.json", {"state": "ready", "indexed_files": {}})
    path = store.config.directory("vault") / "projects" / "additional" / "note.md"
    path.parent.mkdir(parents=True)
    path.write_text("A different project", encoding="utf-8")
    assert store.status()["index"]["state"] == "ready"


def test_cross_project_failure_preserves_successful_project_results(store, monkeypatch):
    from research_memory import basic_memory
    write_json(store.data / "enabled-projects.json", {"additional": {"enabled": True, "path": "vault/projects/additional"}})
    def failing_secondary(config, query, mode, project):
        if project == "additional":
            raise RuntimeError("Index unavailable")
        return {"is_error": False, "data": {"results": ["valid primary result"]}}
    monkeypatch.setattr(basic_memory, "search", failing_secondary)
    result = search_all(store.config, "example")
    assert result["is_error"]
    assert result["projects"][store.config.project_id]["data"]["results"] == ["valid primary result"]
    assert result["projects"]["additional"]["is_error"]
