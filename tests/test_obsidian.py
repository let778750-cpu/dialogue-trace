import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import sys
import tomllib
import zipfile

import pytest
from research_memory import cli
from research_memory.host_config import ensure_mcp_server
from research_memory.knowledge import Knowledge
from research_memory.obsidian import Obsidian, ObsidianError, IDENTITY, create_server
from research_memory.storage import Conflict, atomic, read_json, write_json


def test_mcp_configuration_preserves_user_settings_and_other_servers(store):
    path = store.config.root / ".codex/config.toml"
    original = '# Keep my settings\nmodel = "my-model"\n[mcp_servers.other]\ncommand = "other"\n'
    atomic(path, original.encode())
    settings = {"command": "python", "args": ["D:\\research path\\bridge.py"], "tool_timeout_sec": 60}
    ensure_mcp_server(store.config, "research_obsidian", settings)
    configured = path.read_text()
    assert configured.startswith(original)
    ensure_mcp_server(store.config, "research_obsidian", settings)
    assert path.read_text() == configured
    assert tomllib.loads(configured)["mcp_servers"]["other"]["command"] == "other"
    with pytest.raises(Conflict):
        ensure_mcp_server(store.config, "research_obsidian", dict(settings, command="different"))
    assert path.read_text() == configured


def test_export_excludes_plugin_credentials_but_preserves_notes(store, monkeypatch, capsys):
    vault = store.config.directory("vault")
    atomic(vault / "Notes/example.md", b"Research content")
    write_json(vault / ".obsidian/plugins/obsidian-local-rest-api/data.json", {"apiKey": "secret-value"})
    atomic(vault / ".obsidian/plugins/another-plugin/data.json", b'{"token":"private"}')
    monkeypatch.setattr(sys, "argv", ["research-memory", "--root", str(store.config.root), "export"])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    with zipfile.ZipFile(result["path"]) as archive:
        assert archive.read("vault/Notes/example.md") == b"Research content"
        assert not any(".obsidian/plugins" in name for name in archive.namelist())


def test_concurrent_mcp_configuration_keeps_both_entries(store):
    def configure(name):
        return ensure_mcp_server(store.config, name, {"command": "python", "args": [name]})
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(configure, ["memory", "obsidian"])) == ["added", "added"]
    parsed = tomllib.loads((store.config.root / ".codex/config.toml").read_text())
    assert set(parsed["mcp_servers"]) == {"memory", "obsidian"}


@pytest.mark.parametrize("path", ["../outside.md", "/absolute.md", "Notes/../Research.md", ".obsidian/plugins/data.json",
                                  "Notes/secret.md:stream", "Notes\\file.md", "Notes/%2e%2e/file.md", "Notes/a. /b.md",
                                  "projects/other/note.md", "missing.md"])
def test_private_escape_secondary_and_missing_paths_rejected(store, path):
    atomic(store.config.directory("vault") / "projects/other/note.md", b"Other project")
    with pytest.raises(ObsidianError):
        Obsidian(store.config).path(path)


def test_wrong_vault_identity_rejected(store):
    bridge = Obsidian(store.config)
    expected = {"project_id": store.config.project_id, "vault_instance": "ours"}
    write_json(bridge.vault / IDENTITY, expected)
    bridge.verify_identity({"content": json.dumps(expected)})
    with pytest.raises(ObsidianError, match="wrong_vault"):
        bridge.verify_identity({"content": json.dumps(dict(expected, vault_instance="another"))})


def test_missing_open_and_unapproved_command_never_contact_app(store, monkeypatch):
    bridge = Obsidian(store.config)
    def forbidden():
        pytest.fail("Should reject before contacting the app")
    monkeypatch.setattr(bridge, "connected", forbidden)
    with pytest.raises(ObsidianError):
        asyncio.run(bridge.open("Notes/not-created.md"))
    with pytest.raises(ObsidianError):
        asyncio.run(bridge.execute_view("app:delete-file"))
    assert not (bridge.vault / "Notes/not-created.md").exists()


def test_local_mcp_starts_when_obsidian_offline(store):
    async def check():
        from fastmcp import Client
        async with Client(create_server(store.config)) as client:
            result = await client.call_tool("obsidian_status")
            assert result.data["state"] == "unavailable"
            assert result.data["raw_capture_dependency"] is False
    asyncio.run(check())


def publication(event_id):
    return {"processor": "test-obsidian-v1", "event_ids": [event_id], "notes": [{
        "id": "idea-bridge", "type": "idea", "title": "Bridge candidate", "workstream_id": "system-development",
        "authors": ["user"], "conditions": ["condition A"], "sources": [{"event_id": event_id, "quote": "Only under condition A"}],
        "body": "A candidate, not a validated result.", "expected_version": 0}]}


def test_publication_receipt_is_idempotent_and_rejects_invented_sources(store, event):
    bridge = Obsidian(store.config)
    event_id = store.capture(event)
    batch = publication(event_id)
    result = bridge.publish("first", batch)
    assert bridge.publish("first", batch) == result
    assert len(list((store.data / "revisions/idea-bridge").glob("*.json"))) == 1
    batch["notes"][0]["body"] = "Changed content"
    with pytest.raises(Conflict):
        bridge.publish("first", batch)
    batch["notes"][0]["sources"][0]["quote"] = "Fabricated quotation"
    with pytest.raises(ValueError):
        bridge.publish("bad-quote", batch)
    with pytest.raises(Conflict, match="incomplete or unknown"):
        bridge.publish("bad-quote", batch)


def test_publication_preserves_human_edit(store, event):
    bridge = Obsidian(store.config)
    batch = publication(store.capture(event))
    bridge.publish("create", batch)
    path = bridge.vault / "Notes/idea-bridge.md"
    human = path.read_bytes() + b"\nHuman observation\n"
    atomic(path, human)
    batch["notes"][0]["expected_version"] = 1
    with pytest.raises(Conflict, match="Human edit"):
        bridge.publish("update", batch)
    assert path.read_bytes() == human


def test_publication_persistence_failure_prevents_note_write(store, event, monkeypatch):
    batch = publication(store.capture(event))
    def fail(*args, **kwargs):
        raise OSError("disk unavailable")
    monkeypatch.setattr("research_memory.obsidian.write_json", fail)
    with pytest.raises(OSError):
        Obsidian(store.config).publish("disk-failed", batch)
    assert not Knowledge(store).records()


def test_connection_exception_does_not_expose_credential(store, monkeypatch):
    import httpx2
    bridge = Obsidian(store.config)
    def fail():
        raise RuntimeError("Authorization: Bearer must-never-appear")
    monkeypatch.setattr(bridge, "credentials", fail)
    result = asyncio.run(bridge.status())
    assert result["state"] == "unavailable"
    assert "must-never-appear" not in json.dumps(result)


def test_disabled_project_prevents_publication(store, event):
    batch = publication(store.capture(event))
    config = read_json(store.config.path)
    write_json(store.config.path, dict(config, enabled=False))
    with pytest.raises(ObsidianError, match="project_disabled"):
        Obsidian(store.config).publish("disabled", batch)
