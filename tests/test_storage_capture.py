from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from research_memory.storage import Conflict, Store, atomic, read_json, write_json
from research_memory.capture import Transcript, hook


def test_long_multilingual_raw_dedup_and_conflict(store, event):
    event["payload"]["text"] = ("科研假设与反例\nquoted \"condition\" " * 20000)
    first = store.capture(event)
    assert store.capture(event) == first
    assert store.get(first)["event"]["payload"] == event["payload"]
    assert store.status()["captured"] == 1
    event["payload"]["text"] += " changed"
    with pytest.raises(Conflict):
        store.capture(event)
    assert store.get(first)["event"]["payload"]["text"].endswith('"condition" ')


def test_parallel_capture_is_idempotent(store, event):
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda i: store.capture(dict(event, source_id=f"message-{i % 12}")), range(48)))
    assert len(set(ids)) == 12
    assert store.status()["captured"] == 12


def test_repair_after_catalog_commit_failed(store, event, monkeypatch):
    original = store._insert
    monkeypatch.setattr(store, "_insert", lambda *args: (_ for _ in ()).throw(OSError("disk failed")))
    with pytest.raises(OSError):
        store.capture(event)
    monkeypatch.setattr(store, "_insert", original)
    assert store.repair()["valid_events"] == 1
    assert store.status()["pending"] == 1


def test_receipts_do_not_advance_over_unread_data(store, event):
    a = store.capture(event)
    b = store.capture(dict(event, source_id="second"))
    with pytest.raises(ValueError):
        store.acknowledge(["missing"], "test", [], "none")
    store.acknowledge([b], "test/v1", [], "No candidate after full review")
    assert [e["event"]["event_id"] for e in store.pending()] == [a]
    store.repair()
    assert store.status()["organized"] == 1


def test_oversized_event_not_truncated(store, event):
    event["payload"]["text"] = "中文" * 50000
    store.capture(event)
    store.capture(dict(event, source_id="next"))
    pending = store.pending(characters=40)
    assert len(pending) == 1
    assert pending[0]["event"]["payload"] == event["payload"]


def line(payload):
    return (json.dumps({"timestamp": "2026-09-08T00:00:00Z", "type": "response_item", "payload": payload}) + "\n").encode()


def test_transcript_tail_backfill_excludes_private_content(store):
    path = store.config.root / "host.jsonl"
    user = line({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "完整用户提示词"}]})
    hidden = line({"type": "reasoning", "encrypted_content": "PRIVATE_ENCRYPTED_SENTINEL", "content": "PRIVATE_ANALYSIS"})
    analysis = line({"type": "message", "role": "assistant", "channel": "analysis", "content": [{"type": "output_text", "text": "PRIVATE_ANALYSIS"}]})
    public = line({"type": "message", "role": "assistant", "channel": "commentary", "content": [{"type": "output_text", "text": "公开解释和候选想法"}]})
    atomic(path, user + hidden + analysis + public[:-8])
    transcript = Transcript(store)
    first = transcript.ingest(path, "fixture", "system-development")
    assert first["state"] == "gap"
    assert first["captured"] == 1
    atomic(path, user + hidden + analysis + public)
    assert transcript.ingest(path, "fixture", "system-development")["captured"] == 1
    assert store.status()["captured"] == 2
    all_text = "".join(p.read_text(encoding="utf-8") for p in store.events.glob("*.json"))
    assert "PRIVATE_" not in all_text
    assert "公开解释和候选想法" in all_text
    assert transcript.ingest(path, "fixture", "system-development")["captured"] == 0


def test_transcript_corruption_stops_cursor(store):
    path = store.config.root / "host.jsonl"
    public = line({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "A"}]})
    atomic(path, public + b"{bad json}\n" + public)
    result = Transcript(store).ingest(path, "fixture", "system-development")
    assert result["offset"] == len(public)
    assert result["issues"][0]["kind"] == "invalid_json"
    assert store.status()["captured"] == 1


def test_bounded_replay_reads_all_ranges(store):
    path = store.config.root / "host.jsonl"
    atomic(path, b"".join(line({"type": "message", "role": "user", "content": [{"type": "input_text", "text": str(i)}]}) for i in range(11)))
    adapter = Transcript(store)
    results = [adapter.ingest(path, "fixture", "system-development", max_lines=3) for _ in range(4)]
    assert results[-1]["state"] == "caught_up"
    assert store.status()["captured"] == 11


def test_hook_configuration_does_not_claim_desktop_proof(store):
    from research_memory.continuity import Continuity
    Continuity(store).bind(store.config.root,"fixture","system-development",create=True)
    result = hook(store, {"hook_event_name": "SessionStart", "cwd": str(store.config.root), "session_id": "fixture"})
    assert "hookSpecificOutput" in result
    assert store.status()["hooks"]["state"] == "observed_unattested"


def test_path_escape_and_disabled_capture(store, event):
    with pytest.raises(ValueError):
        store.config.inside("../outside")
    store.config.value["enabled"] = False
    with pytest.raises(RuntimeError):
        store.capture(event)


def test_corrupt_event_is_detected(store, event):
    event_id = store.capture(event)
    path = store.events / (event_id + ".json")
    record = read_json(path)
    record["event"]["payload"]["text"] = "corrupt"
    write_json(path, record)
    with pytest.raises(ValueError):
        store.get(event_id)
    assert len(store.repair()["corrupt"]) == 1
