from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: bytes):
    return hashlib.sha256(value).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic(path: Path, value: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path, value):
    atomic(Path(path), encode(value))


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
        raise ValueError("IDs must contain 1-100 ASCII letters, digits, underscore or hyphen")
    return value


class Conflict(RuntimeError):
    pass


class Config:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get("RESEARCH_MEMORY_ROOT") or Path(__file__).resolve().parents[2]).resolve()
        self.path = self.root / "config.json"
        self.value = read_json(self.path)
        if not self.value:
            raise ValueError(f"Missing project config: {self.path}")
        self.package_root = Path(os.environ.get('RESEARCH_MEMORY_PACKAGE_ROOT') or self.value.get('installation_root') or Path(__file__).resolve().parents[2]).resolve()
        self.project_id = safe_id(self.value["project_id"])
        for name in self.value["paths"]:
            self.directory(name).mkdir(parents=True, exist_ok=True)

    def inside(self, path):
        path = (self.root / path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Path escapes project root: {path}")
        return path

    def directory(self, name):
        return self.inside(self.value["paths"][name])

    def input_path(self, path):
        """Inputs may live in explicitly registered workspaces; outputs remain inside the instance."""
        candidate = (self.root / path).resolve()
        roots = [self.root, self.package_root, *(Path(p).resolve() for p in self.value.get('workspaces', []))]
        if not any(candidate.is_relative_to(root) for root in roots):
            raise ValueError('Input is outside this instance and its registered workspaces')
        return candidate

    def environment(self):
        runtime = self.directory("runtime")
        overrides = {
            "RESEARCH_MEMORY_ROOT": str(self.root), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1",
            "RESEARCH_MEMORY_PACKAGE_ROOT": str(self.package_root),
            "TEMP": str(runtime / "tmp"), "TMP": str(runtime / "tmp"),
            "PIP_CACHE_DIR": str(runtime / "cache/pip"), "UV_CACHE_DIR": str(runtime / "cache/uv"),
            "UV_PYTHON_INSTALL_DIR": str(runtime / "python"), "XDG_CACHE_HOME": str(runtime / "cache"),
            "HF_HOME": str(runtime / "models/huggingface"), "FASTEMBED_CACHE_PATH": str(runtime / "models/fastembed"),
            "BASIC_MEMORY_HOME": str(self.directory("vault")),
            "BASIC_MEMORY_CONFIG_DIR": str(runtime / "basic-memory"),
            "BASIC_MEMORY_AUTO_UPDATE": "false", "BASIC_MEMORY_SEMANTIC_SEARCH_ENABLED": "true",
            "BASIC_MEMORY_SEMANTIC_EMBEDDING_PROVIDER": "fastembed",
            "BASIC_MEMORY_SEMANTIC_EMBEDDING_MODEL": self.value["embedding"]["model"],
            "BASIC_MEMORY_SEMANTIC_EMBEDDING_DIMENSIONS": str(self.value["embedding"]["dimensions"]),
            "BASIC_MEMORY_SEMANTIC_EMBEDDING_CACHE_DIR": str(runtime / "models/fastembed"),
            "BASIC_MEMORY_SEMANTIC_EMBEDDING_THREADS": "4",
            "BASIC_MEMORY_SEMANTIC_MIN_SIMILARITY": str(self.value.get("retrieval", {}).get("min_similarity", 0.35)),
            "TIKTOKEN_CACHE_DIR": str(runtime / "cache/tiktoken"),
            "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
        }
        for key in ("TEMP", "BASIC_MEMORY_CONFIG_DIR", "HF_HOME", "FASTEMBED_CACHE_PATH", "XDG_CACHE_HOME"):
            Path(overrides[key]).mkdir(parents=True, exist_ok=True)
        return dict(os.environ, **overrides)


class Store:
    """Event files are canonical; SQLite is a recoverable lookup/queue index."""

    def __init__(self, config: Config, recover=False):
        self.config = config
        self.data = config.directory("data")
        self.events = self.data / "events"
        self.events.mkdir(exist_ok=True)
        self.db_path = self.data / "catalog.sqlite"
        self.catalog_error = None
        try:
            self.initialize_catalog()
        except sqlite3.DatabaseError as exc:
            if getattr(exc, "sqlite_errorcode", 0) not in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
                raise
            if not recover:
                self.catalog_error = str(exc)
                return
            with self.lock():
                for name in ("catalog.sqlite", "catalog.sqlite-wal", "catalog.sqlite-shm"):
                    path = self.data / name
                    if path.exists():
                        quarantine = self.data / "quarantine" / (uuid.uuid4().hex + "-" + name)
                        quarantine.parent.mkdir(exist_ok=True)
                        os.replace(path, quarantine)
                self.initialize_catalog()
            self.repair()

    def initialize_catalog(self):
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    position INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL, hash TEXT NOT NULL,
                    workstream TEXT NOT NULL, session TEXT NOT NULL, kind TEXT NOT NULL,
                    captured_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS processed (
                    event_id TEXT PRIMARY KEY, receipt TEXT NOT NULL);
            """)
            if "research_project" not in {r[1] for r in db.execute("PRAGMA table_info(events)")}:
                db.execute("ALTER TABLE events ADD COLUMN research_project TEXT")

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def lock(self, name="store", timeout=20):
        # OS byte-range locks release on process death, unlike PID lockfiles.
        path = self.data / "locks" / (safe_id(name) + ".lock")
        path.parent.mkdir(exist_ok=True)
        with path.open("a+b") as stream:
            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Lock timeout: {name}")
                    time.sleep(0.02)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def capture(self, event):
        if not self.config.value["enabled"]:
            raise RuntimeError("Project recording is disabled")
        allowed = {"message", "tool_call", "tool_result", "lifecycle", "run_intent", "run_started", "run_finished", "source", "decision"}
        if event.get("kind") not in allowed:
            raise ValueError("Unsupported or private event kind")
        if event.get("author") in {"system", "developer", "analysis", "reasoning"}:
            raise ValueError("Only public events are accepted")
        for key in ("source", "source_id", "session_id", "workstream_id", "payload"):
            if key not in event:
                raise ValueError(f"Missing event field: {key}")
        if event['workstream_id'] is not None:
            safe_id(event["workstream_id"])
        elif not event.get('research_project_id'):
            raise ValueError('Unassigned events require an explicit research project')
        identity = [self.config.project_id, event["source"], event["session_id"], event["source_id"]]
        event_id = "ev_" + digest(encode(identity))[:40]
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.config)
        existing = read_json(self.events / (event_id + ".json"))
        if existing:
            # Routing is maintained separately; re-import must retain the first raw owner.
            event = dict(event, workstream_id=existing['event']['workstream_id'])
        if projects.active:
            if existing:
                owner = projects.event_project(existing["event"])
                if event.get("research_project_id") and event["research_project_id"] != owner:
                    raise Conflict("Existing event belongs to another research project")
                # Preserve the shape/hash of legacy source records during idempotent re-ingestion.
                if "research_project_id" in existing["event"]:
                    event = dict(event, research_project_id=owner)
                else:
                    event = {k: v for k, v in event.items() if k != "research_project_id"}
            else:
                owner = projects.context(event.get("research_project_id"), event["workstream_id"])
                event = dict(event, research_project_id=owner)
        payload = {key: value for key, value in event.items() if key not in {"event_id", "captured_at", "project_id"}}
        payload.update(project_id=self.config.project_id, event_id=event_id)
        content_hash = digest(encode(payload))
        envelope = {"schema_version": 1, "captured_at": now(), "content_hash": content_hash, "event": payload}
        path = self.events / (event_id + ".json")
        with self.lock():
            if path.exists():
                old = read_json(path)
                if old["content_hash"] != content_hash:
                    write_json(self.data / "conflicts" / f"{event_id}-{uuid.uuid4().hex}.json", envelope)
                    raise Conflict("Source ID reused for different event content")
                envelope = old
            else:
                write_json(path, envelope)
            with self.db() as db:
                self._insert(db, envelope)
        return event_id

    def _insert(self, db, envelope):
        e = envelope["event"]
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.config)
        owner = projects.event_project(e)
        db.execute("INSERT INTO events(event_id,hash,workstream,session,kind,captured_at,research_project) VALUES(?,?,?,?,?,?,?) "
                   "ON CONFLICT(event_id) DO UPDATE SET research_project=excluded.research_project, workstream=excluded.workstream",
                   (e["event_id"], envelope["content_hash"], projects.event_workstream(e) or '', e["session_id"], e["kind"], envelope["captured_at"], owner))

    def get(self, event_id):
        envelope = read_json(self.events / (safe_id(event_id) + ".json"))
        if not envelope or digest(encode(envelope["event"])) != envelope["content_hash"]:
            raise ValueError(f"Missing or corrupt event: {event_id}")
        return envelope

    def pending(self, workstream=None, limit=None, characters=None, project=None):
        limit = limit or self.config.value["capture"]["max_batch_events"]
        characters = characters or self.config.value["capture"]["max_batch_characters"]
        query = "SELECT e.* FROM events e LEFT JOIN processed p USING(event_id) WHERE p.event_id IS NULL"
        args = []
        if workstream:
            query += " AND workstream=?"
            args.append(workstream)
        if project:
            query += " AND research_project=?"
            args.append(project)
        query += " ORDER BY position LIMIT ?"
        with self.db() as db:
            rows = db.execute(query, (*args, limit)).fetchall()
        result, used = [], 0
        for row in rows:
            item = self.get(row["event_id"])
            size = len(encode(item).decode("utf-8"))
            if result and used + size > characters:
                break
            # A single oversized event remains whole; the skill can read it by reference.
            result.append(item)
            used += size
        return result

    def acknowledge(self, event_ids, processor, notes, reason=None):
        if not processor or (not notes and not reason):
            raise ValueError("Receipt requires processor and notes or explicit no-candidate reason")
        for event_id in event_ids:
            self.get(event_id)
        receipt_id = "receipt_" + uuid.uuid4().hex
        receipt = dict(id=receipt_id, event_ids=event_ids, processor=processor, notes=notes, reason=reason, at=now())
        with self.lock():
            write_json(self.data / "receipts" / (receipt_id + ".json"), receipt)
            with self.db() as db:
                db.executemany("INSERT OR REPLACE INTO processed VALUES(?,?)", [(e, receipt_id) for e in event_ids])
        return receipt

    def repair(self):
        result = {"valid_events": 0, "corrupt": [], "unfinished_files": []}
        with self.lock():
            with self.db() as db:
                db.execute("DELETE FROM events")
                db.execute("DELETE FROM processed")
                envelopes = []
                for path in self.events.glob("*.json"):
                    try:
                        envelope = self.get(path.stem)
                        envelopes.append(envelope)
                        result["valid_events"] += 1
                    except (ValueError, KeyError):
                        result["corrupt"].append(str(path))
                for envelope in sorted(envelopes, key=lambda e: (e["captured_at"], e["event"]["event_id"])):
                    self._insert(db, envelope)
                for path in sorted((self.data / "receipts").glob("*.json")):
                    receipt = read_json(path)
                    db.executemany("INSERT OR REPLACE INTO processed SELECT event_id,? FROM events WHERE event_id=?",
                                   [(receipt["id"], e) for e in receipt["event_ids"]])
            result["unfinished_files"] = [str(p) for p in self.data.rglob("*.tmp")]
            write_json(self.data / "health" / "integrity.json", dict(result, checked_at=now()))
        return result

    def status(self, project=None):
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.config)
        if project:
            projects.get(project)
        with self.db() as db:
            where, params = (' WHERE research_project=?', (project,)) if project else ('', ())
            captured = db.execute("SELECT count(*) FROM events" + where, params).fetchone()[0]
            organized = db.execute("SELECT count(*) FROM processed JOIN events USING(event_id)" + where, params).fetchone()[0]
        selected = project or projects.default
        index_file = "index.json" if selected == self.config.project_id else f"index-{selected}.json"
        index = read_json(self.data / "health" / index_file, {"state": "not_verified"})
        vault = projects.folder(selected) if projects.active else self.config.directory("vault")
        current = {str(p.relative_to(vault)): file_hash(p) for p in vault.rglob("*.md")
                   if projects.active or not p.is_relative_to(vault / "projects")}
        snapshots = index.get("components", {"last_operation": index})
        for component in snapshots.values():
            if component.get("state") == "ready" and component.get("indexed_files") != current:
                component["state"] = "stale"
        if index.get("state") == "ready" and any(c.get("state") == "stale" for c in snapshots.values()):
            index["state"] = "stale"
        return {"enabled": self.config.value["enabled"], "project_id": self.config.project_id,
                "captured": captured, "organized": organized, "pending": captured - organized,
                "index": index, "index_project": selected, "capture_scope": project or "archive",
                "hooks": read_json(self.data / "health" / "hooks.json", {"state": "not_observed"}),
                "integrity": read_json(self.data / "health" / "integrity.json", {"state": "not_checked"}),
                "gaps": [read_json(p) for p in (self.data / "gaps").glob("*.json") if read_json(p).get("state") != "resolved"]}
