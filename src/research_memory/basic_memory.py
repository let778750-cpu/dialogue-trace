from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from .storage import Config, now, write_json, read_json, file_hash


def configure(config):
    os.environ.update(config.environment())
    os.environ["BASIC_MEMORY_FORCE_LOCAL"] = "true"
    os.environ["BASIC_MEMORY_EXPLICIT_ROUTING"] = "true"


def cli(config, args, timeout=300):
    env = config.environment()
    env["BASIC_MEMORY_FORCE_LOCAL"] = "true"
    result = subprocess.run([sys.executable, "-m", "research_memory.bm_entry", *args],
                            cwd=config.root, env=env, capture_output=True, timeout=timeout)
    return {"exit_code": result.returncode, "stdout": result.stdout.decode("utf-8", errors="replace"),
            "stderr": result.stderr.decode("utf-8", errors="replace")}


def sync(config, embeddings=False, project=None):
    from .projects import resolve, configure_indexes
    configure_indexes(config)
    project, vault = resolve(config, project)
    # Upstream --embeddings alone only sees existing DB rows, so it can embed
    # deleted names and miss new files. A requested vector refresh first scans.
    command = ["reindex", "--project", project] + ([] if embeddings else ["--search"])
    result = cli(config, command, timeout=1800)
    health = {"state": "ready" if result["exit_code"] == 0 else "failed", "at": now(), "embeddings": embeddings,
              "exit_code": result["exit_code"], "error": result["stderr"][-3000:] if result["exit_code"] else None}
    if result["exit_code"] == 0:
        import re
        if any(int(count) for count in re.findall(r'(\d+) errors', result['stdout'])):
            health['state'] = 'degraded'
            health['error'] = 'Some upstream embeddings failed; inspect the retained command output'
        health["indexed_files"] = {str(p.relative_to(vault)): file_hash(p)
                                    for p in vault.rglob("*.md") if project != config.project_id or not p.is_relative_to(vault / "projects")}
        from .research_projects import ResearchProjects
        if ResearchProjects(config).active:
            health['relations'] = relation_health(config, project)
            if health['relations'].get('local_unresolved'):
                health['state'] = 'degraded'
    path = config.directory("data") / "health" / ("index.json" if project == config.project_id else f"index-{project}.json")
    previous = read_json(path, {})
    components = previous.get("components", {})
    components["embeddings" if embeddings else "text"] = health.copy()
    if embeddings and result['exit_code'] == 0:
        components['text'] = dict(health, embeddings=False)
    health["components"] = components
    if any(c["state"] == "failed" for c in components.values()):
        health["state"] = "degraded"
    write_json(path, health)
    return result


def relation_health(config, project):
    """Report the pinned backend's cross-project write limitation without changing it."""
    import sqlite3
    from .bm_entry import project_reference
    path = config.directory('runtime') / 'basic-memory/memory.db'
    if not path.exists():
        return {'state': 'not_verified'}
    try:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            rows = db.execute('''SELECT r.to_name, r.to_id FROM relation r
                JOIN entity e ON e.id=r.from_id JOIN project p ON p.id=e.project_id
                WHERE p.name=? AND r.relation_type != 'links_to'
                  AND json_extract(e.entity_metadata, '$.id') IS NOT NULL''', (project,)).fetchall()
        local = cross = 0
        for target, resolved in rows:
            if resolved is not None: continue
            converted = project_reference(config, target)
            if '::' in converted and converted.split('::', 1)[0] != project: cross += 1
            else: local += 1
        return {'state': 'partial_cross_project' if cross else ('degraded' if local else 'ready'),
                'typed_total':len(rows), 'local_unresolved':local, 'cross_project_unresolved':cross,
                'cross_project_authority':'canonical notes and research graph; BM 0.23.2 target write guard requires same project'}
    except sqlite3.Error as exc:
        return {'state':'not_verified','error':type(exc).__name__}


async def tool_call(config, name, args):
    from .projects import resolve
    project, _ = resolve(config, args.get("project"))
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    transport = StdioTransport(command=sys.executable, args=["-m", "research_memory.cli", "--root", str(config.root), "bm-mcp", "--project", project],
                               env=config.environment(), cwd=str(config.root))
    async with Client(transport) as client:
        result = await client.call_tool(name, args)
        return {"is_error": result.is_error, "data": result.data,
                "content": [c.model_dump(mode="json") for c in result.content]}


def search(config, query, mode="text", project=None):
    from .projects import resolve
    project, _ = resolve(config, project)
    return asyncio.run(tool_call(config, "search_notes", {"query": query, "project": project or config.project_id,
                                                         "search_type": mode, "page_size": 10, "output_format": "json"}))


def serve(config, project=None):
    from .projects import resolve
    project, _ = resolve(config, project)
    configure(config)
    from .bm_entry import install
    install(config)
    from basic_memory.cli.main import app
    sys.argv = ["basic-memory", "mcp", "--project", project]
    app()
