import json
from pathlib import Path
import pytest
from research_memory.storage import Config, Store, write_json


@pytest.fixture
def store(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config.example.json").read_text(encoding="utf-8-sig"))
    config["enabled"] = True
    write_json(tmp_path / "config.json", config)
    return Store(Config(tmp_path))


@pytest.fixture
def event():
    return {"source": "fixture", "source_id": "message-1", "session_id": "test-session", "workstream_id": "system-development",
            "kind": "message", "author": "user", "payload": {"text": "Only under condition A, test the alternative."},
            "source_sequence": 1, "occurred_at": "2026-09-01T00:00:00Z"}
