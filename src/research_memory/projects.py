from pathlib import Path
from .storage import Config, Store, safe_id, read_json, write_json, now, atomic


def enabled(config, examples=False):
    from .research_projects import ResearchProjects
    catalog = ResearchProjects(config)
    if catalog.active:
        return {p['id']: catalog.folder(p['id']) for p in catalog.records(examples=examples)}
    registered = read_json(config.directory("data") / "enabled-projects.json", {})
    result = {config.project_id: config.directory("vault")}
    for name, record in registered.items():
        if record["enabled"]:
            result[name] = config.inside(record["path"])
    return result


def resolve(config, project=None):
    from .research_projects import ResearchProjects
    catalog = ResearchProjects(config)
    if catalog.active:
        p = catalog.get(project)
        return p['bm_project'], catalog.folder(p['id'])
    project = project or config.project_id
    if project not in enabled(config):
        raise ValueError("This project-scoped request requires an explicitly enabled project")
    return project, enabled(config)[project]


def search_all(config, query, mode="text", examples=False):
    from .basic_memory import search
    results = {}
    for project in enabled(config, examples):
        try:
            results[project] = search(config, query, mode, project)
        except Exception as exc:
            results[project] = {"is_error": True, "error": type(exc).__name__, "message": str(exc)}
    return {"projects": results, "is_error": any(r.get("is_error") for r in results.values())}


def register(config, project, active=True):
    from .research_projects import ResearchProjects
    catalog = ResearchProjects(config)
    if catalog.active:
        p = catalog.get(project, disabled=True)
        result = catalog.register(project, p['name'], p['goal'], p['kind'], active)
        configure_indexes(config)
        return result
    from .basic_memory import configure
    safe_id(project)
    if project == config.project_id:
        raise ValueError("Use set-enabled for the primary project")
    store = Store(config)
    with store.lock("projects"):
        path = config.directory("vault") / "projects" / project
        registry_path = store.data / "enabled-projects.json"
        registry = read_json(registry_path, {})
        if not active and project not in registry:
            raise ValueError("Unknown registered project")
        path.mkdir(parents=True, exist_ok=True)
        # The primary index must not recursively ingest separately routed projects.
        ignore_path = config.directory("vault") / ".gitignore"
        ignore = ignore_path.read_text(encoding="utf-8") if ignore_path.exists() else ""
        if "/projects/" not in ignore.splitlines():
            atomic(ignore_path, (ignore.rstrip() + "\n/projects/\n").encode("utf-8"))
        configure(config)
        from basic_memory.config import ConfigManager
        manager = ConfigManager()
        if active and project not in manager.projects:
            manager.add_project(project, str(path))
        elif not active and project in manager.projects:
            manager.remove_project(project)
        registry[project] = {"path": path.relative_to(config.root).as_posix(), "enabled": active, "at": now()}
        write_json(registry_path, registry)
        return {"project_id": project, **registry[project]}


def configure_indexes(config):
    """Update only this archive's registered BM projects; never index the outer vault."""
    from .research_projects import ResearchProjects
    from .basic_memory import configure
    catalog = ResearchProjects(config)
    if not catalog.active:
        return {}
    configure(config)
    from basic_memory.config import ConfigManager, ProjectEntry
    manager = ConfigManager()
    settings = manager.load_config()
    retired = set()
    # Fresh BM configuration may create a default `main` at BASIC_MEMORY_HOME.
    # The outer navigation vault must never become a duplicate knowledge index.
    for name, entry in list(settings.projects.items()):
        if Path(entry.path).resolve() == config.directory('vault').resolve():
            settings.projects.pop(name)
            retired.add(name)
    result = {}
    for p in catalog.records(examples=True, disabled=True):
        name = p['bm_project']
        if p['enabled']:
            path = str(catalog.folder(p['id']))
            old = settings.projects.get(name)
            settings.projects[name] = old.model_copy(update={'path': path}) if old else ProjectEntry(path=path)
            result[name] = path
        else:
            settings.projects.pop(name, None)
            retired.add(name)
    settings.default_project = catalog.get()['bm_project']
    manager.save_config(settings)
    # Existing BM databases reconcile paths from their project rows, so changing
    # config alone is insufficient. Use its public move command (no file moves).
    database = config.directory('runtime') / 'basic-memory/memory.db'
    if database.exists():
        import sqlite3
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            existing = dict(db.execute('SELECT name,path FROM project'))
        from .basic_memory import cli
        retired.update(name for name, path in existing.items()
                       if Path(path).resolve() == config.directory('vault').resolve())
        for name in sorted(retired - result.keys()):
            if name in existing:
                # Only disposable index rows are removed. Do not use --delete-notes.
                removed = cli(config, ['project', 'remove', name, '--local'])
                if removed['exit_code']:
                    raise RuntimeError('Basic Memory retired index removal failed: ' + name)
        for name, path in result.items():
            if name in existing and Path(existing[name]).resolve() != Path(path).resolve():
                moved = cli(config, ['project', 'move', name, path])
                if moved['exit_code']:
                    raise RuntimeError('Basic Memory project path update failed: ' + name)
    return result
