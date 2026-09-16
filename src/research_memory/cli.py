from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import traceback
import zipfile
from .storage import Config, Store, now, read_json, write_json, atomic, encode


def load(value):
    return json.load(sys.stdin) if value == "-" else read_json(Path(value))


def parser():
    p = argparse.ArgumentParser(prog="research-memory")
    p.add_argument("--root")
    sub = p.add_subparsers(dest="command", required=True)
    sp = sub.add_parser('research')
    sp.add_argument('operation')
    sp.add_argument('--file')
    sp = sub.add_parser('research-mcp')
    sp = sub.add_parser('setup')
    sp.add_argument('--workspace', required=True)
    sp.add_argument('--name', default='我的研究')
    sp.add_argument('--with-obsidian', action='store_true')
    sp = sub.add_parser('attach-obsidian')
    sp.add_argument('--vault')
    sp = sub.add_parser('configure-host')
    sp.add_argument('--workspace', required=True)
    for name in ("status", "reconcile", "init", "bm-mcp", "views", "export", "doctor", "projects", "timeline", 'uninstall'):
        sp = sub.add_parser(name)
        if name in {"bm-mcp", "views", "status", "reconcile"}:
            sp.add_argument("--project")
    sp = sub.add_parser('project-register')
    sp.add_argument('project_id')
    sp.add_argument('--name', required=True)
    sp.add_argument('--goal', default='')
    sp.add_argument('--kind', choices=['research', 'example'], default='research')
    sp = sub.add_parser('graph-entries')
    sp.add_argument('--project', required=True)
    sp.add_argument('--workstream')
    sp.add_argument('--entry', action='append', default=[])
    sp.add_argument('--expected-version', type=int, required=True)
    for name in ("project-enable", "project-disable"):
        sp = sub.add_parser(name)
        sp.add_argument("project_id")
    for name in ("capture-event", "commit", "checkpoint", "timeline-annotate"):
        sp = sub.add_parser(name)
        sp.add_argument("--file", required=True)
    sp = sub.add_parser("bind")
    sp.add_argument("--cwd")
    sp.add_argument("--session", required=True)
    sp.add_argument("--workstream")
    sp.add_argument("--goal")
    sp.add_argument("--create", action="store_true")
    sp.add_argument('--project')
    sp.add_argument('--after-event')
    sp = sub.add_parser("ingest")
    sp.add_argument("--transcript", required=True)
    sp.add_argument("--session", required=True)
    sp.add_argument("--workstream")
    sp.add_argument('--project')
    sp.add_argument("--max-lines", type=int, default=10000)
    sp.add_argument("--restart", action="store_true")
    sp = sub.add_parser("event")
    sp.add_argument("event_id")
    sp.add_argument("--start", type=int, default=0)
    sp.add_argument("--length", type=int, default=12000)
    for name in ("resume", "pending"):
        sp = sub.add_parser(name)
        sp.add_argument("--workstream", required=True)
        sp.add_argument('--project')
    sp = sub.add_parser("run")
    sp.add_argument("--file", required=True)
    sp.add_argument("--background", action="store_true")
    sp = sub.add_parser("worker")
    sp.add_argument("run_id")
    sp = sub.add_parser("resolve-run")
    sp.add_argument("run_id")
    sp.add_argument("--status", required=True)
    sp.add_argument("--evidence", required=True)
    sp = sub.add_parser("graph")
    sp.add_argument("focus")
    sp.add_argument("--depth", type=int, default=1)
    sp.add_argument('--cross-project', action='store_true')
    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("--mode", choices=["text", "vector", "hybrid"], default="text")
    sp.add_argument("--project")
    sp.add_argument("--all-enabled", action="store_true")
    sp.add_argument('--include-examples', action='store_true')
    sp = sub.add_parser("reindex")
    sp.add_argument("--embeddings", action="store_true")
    sp.add_argument("--project")
    sp = sub.add_parser("set-enabled")
    sp.add_argument("value", choices=["true", "false"])
    sp = sub.add_parser("accept-human-edit")
    sp.add_argument("note_id")
    sp.add_argument("--hash", required=True)
    sub.add_parser("readability-plan")
    sub.add_parser('structure-plan')
    for name in ('structure-apply', 'structure-rollback'):
        sp = sub.add_parser(name)
        sp.add_argument('--file', required=True)
    for name in ("readability-apply", "readability-rollback"):
        sp = sub.add_parser(name)
        sp.add_argument("--file", required=True)
    sp = sub.add_parser("hook")
    sp.add_argument("--file", default="-")
    sp = sub.add_parser("bm")
    sp.add_argument("args", nargs=argparse.REMAINDER)
    return p


def initialize(config, store):
    from .continuity import Continuity
    from .knowledge import Knowledge
    from .research_projects import ResearchProjects
    if ResearchProjects(config).active:
        from .projects import configure_indexes
        configure_indexes(config)
        return {"state": "already_configured", "root": str(config.root),
                "message": "Existing project layout and host settings preserved; use doctor to inspect health"}
    from .basic_memory import configure
    configure(config)
    from basic_memory.config import ConfigManager
    manager = ConfigManager()
    if config.project_id not in manager.projects:
        manager.add_project(config.project_id, str(config.directory("vault")))
    manager.set_default_project(config.project_id)
    if manager.projects.get("main") == str(config.directory("vault")) and config.project_id != "main":
        manager.remove_project("main")
    Continuity(store).bind(config.root, "project-initialization", create=True)
    Knowledge(store).views()
    python = config.directory("runtime") / "venv/Scripts/python.exe"
    command = f'"{python}" "{config.root / "scripts/hook.py"}"'
    events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop", "PreCompact", "PostCompact", "Interrupt", "SessionEnd"]
    hooks = {"hooks": {name: [{"hooks": [{"type": "command", "command": command,
              "timeout": 3 if name in {"Interrupt", "SessionEnd"} else 15}]}] for name in events}}
    write_json(config.root / ".codex/hooks.json", hooks)
    from .host_config import ensure_mcp_server
    ensure_mcp_server(config, "research_basic_memory", {
        "command": str(python), "args": ["-m", "research_memory.cli", "--root", str(config.root), "bm-mcp"],
        "startup_timeout_sec": 180, "tool_timeout_sec": 180,
    })
    graph = {"search": "-path:Sources", "showTags": False, "showAttachments": False}
    write_json(config.directory("vault") / ".obsidian/graph.json", graph)
    return {"state": "configured_not_desktop_verified", "root": str(config.root), "project_id": config.project_id}


def main():
    args = parser().parse_args()
    if args.command == 'setup':
        from .installation import setup
        print(json.dumps(setup(args.root, args.workspace, args.name, args.with_obsidian), ensure_ascii=False, indent=2))
        return
    config = Config(args.root)
    if args.command == 'research-mcp':
        from .research_mcp import serve
        serve(config)
        return
    if args.command == "bm-mcp":
        from .basic_memory import serve
        serve(config, args.project)
        return
    store = Store(config, recover=args.command == "reconcile")
    from .continuity import Continuity
    from .capture import Transcript, hook
    from .runs import Runs
    from .knowledge import Knowledge
    from . import basic_memory as bm
    from . import projects
    try:
        match args.command:
            case 'research':
                from .research import dispatch
                result = dispatch(store, args.operation, load(args.file) if args.file else {})
            case 'attach-obsidian':
                from .installation import attach_obsidian
                result = attach_obsidian(config, args.vault)
            case 'configure-host':
                from .installation import configure_host
                result = configure_host(config, args.workspace)
            case "init": result = initialize(config, store)
            case "status": result = store.status(args.project)
            case "doctor":
                from .installation import doctor
                result = doctor(config)
            case 'uninstall':
                from .installation import uninstall
                result = uninstall(config)
            case "bind": result = Continuity(store).bind(args.cwd or config.root, args.session, args.workstream, args.goal, args.create, args.project, args.after_event)
            case "graph-entries":
                from .research_projects import ResearchProjects
                result = ResearchProjects(config).set_graph_entries(args.project, args.entry, args.expected_version, args.workstream)
                from .graph_view import publish_projection
                result['projection'] = publish_projection(Knowledge(store))
            case "timeline":
                from .timeline import publish_projection
                result = publish_projection(Knowledge(store))
            case "timeline-annotate":
                from .timeline import annotate
                result = annotate(store, load(args.file))
            case "capture-event":
                result = {"event_id": store.capture(load(args.file))}
                from .timeline import refresh_if_present
                refresh_if_present(store)
            case "ingest": result = Transcript(store).ingest(args.transcript, args.session, args.workstream, args.max_lines, args.restart, args.project)
            case "pending":
                result = []
                from .research_projects import ResearchProjects
                selected = ResearchProjects(config).context(args.project, args.workstream)
                for envelope in store.pending(args.workstream, project=selected):
                    length = len(encode(envelope).decode("utf-8"))
                    if length > config.value["capture"]["max_batch_characters"]:
                        result.append({"event_id": envelope["event"]["event_id"], "oversized": True,
                                       "characters": length, "content_hash": envelope["content_hash"],
                                       "read_command": f"event {envelope['event']['event_id']} --start 0 --length 12000"})
                    else:
                        result.append(envelope)
            case "event":
                if args.start < 0 or not 1 <= args.length <= 50000:
                    raise ValueError("Invalid event page range")
                envelope = store.get(args.event_id)
                text = encode(envelope).decode("utf-8")
                end = min(len(text), args.start + args.length)
                result = {"event_id": args.event_id, "content_hash": envelope["content_hash"],
                          "start": args.start, "end": end, "total": len(text), "next_start": end if end < len(text) else None,
                          "serialized_event_fragment": text[args.start:end]}
            case "commit": result = Knowledge(store).commit(load(args.file))
            case "checkpoint":
                spec = load(args.file)
                result = Continuity(store).checkpoint(spec["workstream_id"], spec["data"], spec["expected_version"])
            case "reconcile": result = {"events": store.repair(), "runs": Runs(store).reconcile(project=args.project)}
            case "resume": result = Continuity(store).resume(args.workstream, args.project)
            case "run": result = Runs(store).start(load(args.file), args.background)
            case "worker": result = Runs(store).execute(args.run_id)
            case "resolve-run": result = Runs(store).resolve(args.run_id, args.status, args.evidence)
            case "graph": result = Knowledge(store).graph(args.focus, args.depth, args.cross_project)
            case "views": result = Knowledge(store).views(args.project)
            case 'structure-plan' | 'structure-apply' | 'structure-rollback':
                from .structure_migration import StructureMigration
                migration = StructureMigration(Knowledge(store))
                result = migration.prepare() if args.command == 'structure-plan' else migration.apply(args.file, rollback=args.command == 'structure-rollback')
            case "readability-plan" | "readability-apply" | "readability-rollback":
                from .migration import ReadabilityMigration
                migration = ReadabilityMigration(Knowledge(store))
                result = migration.prepare() if args.command == "readability-plan" else migration.apply(args.file, rollback=args.command == "readability-rollback")
            case "projects":
                from .research_projects import ResearchProjects
                result = ResearchProjects(config).records(examples=True, disabled=True)
            case 'project-register':
                from .research_projects import ResearchProjects
                result = ResearchProjects(config).register(args.project_id, args.name, args.goal, args.kind)
                projects.configure_indexes(config)
                Knowledge(store).views()
            case "project-enable" | "project-disable": result = projects.register(config, args.project_id, args.command == "project-enable")
            case "search":
                if args.all_enabled and args.project:
                    raise ValueError("Choose --project or --all-enabled")
                if args.include_examples and not args.all_enabled:
                    raise ValueError('--include-examples requires --all-enabled; an explicit --project can select one example')
                result = projects.search_all(config, args.query, args.mode, args.include_examples) if args.all_enabled else bm.search(config, args.query, args.mode, args.project)
            case "reindex": result = bm.sync(config, args.embeddings, args.project)
            case "bm": result = bm.cli(config, args.args)
            case "hook":
                result = hook(store, load(args.file))
                from .timeline import refresh_if_present
                refresh_if_present(store)
            case "accept-human-edit": result = Knowledge(store).accept_human_edit(args.note_id, args.hash)
            case "set-enabled":
                with store.lock("config"):
                    config.value["enabled"] = args.value == "true"
                    write_json(config.path, config.value)
                result = {"enabled": config.value["enabled"]}
            case "export":
                from .host_config import exportable
                path = config.directory("output") / ("research-memory-" + now().replace(":", "-") + ".zip")
                with store.lock():
                    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as archive:
                        for folder in ("vault", "data", "runs", "docs"):
                            for source in (config.root / folder).rglob("*"):
                                if exportable(config, source):
                                    archive.write(source, str(source.relative_to(config.root)))
                        archive.write(config.path, "config.json")
                result = {"path": str(path), "catalog": "rebuild from canonical events and receipts",
                          "excluded": ["Obsidian plugin packages and state (may contain credentials)"]}
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        if isinstance(result, dict) and (result.get("exit_code", 0) not in {0, None} or result.get("is_error")):
            sys.exit(1)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc), "mutation_state": getattr(exc, "mutation_state", "unknown")}, ensure_ascii=False), file=sys.stderr)
        if os.environ.get("RESEARCH_MEMORY_DEBUG"):
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
