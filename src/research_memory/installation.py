"""Portable installation; application files and private research instances are separate."""
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib
import uuid

from .storage import Config, Store, Conflict, atomic, encode, file_hash, now, read_json, write_json


def default_root():
    base = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share'))
    return base / 'ResearchMemory/instances/default'


def template():
    return dict(schema_version=1, project_id='research-'+uuid.uuid4().hex[:12], project_name='我的研究', enabled=True,
                default_workstream='main', paths={k:k for k in ('vault','data','runs','runtime','output','integrations')},
                embedding=dict(provider='fastembed', model='jinaai/jina-embeddings-v2-base-zh', dimensions=768),
                capture=dict(max_batch_events=80,max_batch_characters=50000,require_session_binding=True), resume_character_budget=6500,
                resume_token_budget=2000, retrieval=dict(min_similarity=0.35), workspaces=[])


def ensure_vault_identity(config):
    """The reader checks this identity before accepting any projection."""
    from .research_projects import ResearchProjects, SYSTEM
    path = config.directory('vault') / (SYSTEM if ResearchProjects(config).active else 'System') / 'research-memory-identity.json'
    identity = read_json(path)
    if identity and identity.get('project_id') != config.project_id:
        raise Conflict('Existing vault identity belongs to another archive: '+str(path))
    if not identity:
        write_json(path, dict(project_id=config.project_id, vault_instance=uuid.uuid4().hex))


def setup(root=None, workspace=None, name='我的研究', with_obsidian=False):
    root = Path(root or default_root()).resolve()
    package = Path(os.environ.get('RESEARCH_MEMORY_PACKAGE_ROOT') or Path(__file__).resolve().parents[2]).resolve()
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError('Workspace must be an existing directory')
    if root == package or root.is_relative_to(package):
        raise ValueError('New private instances must be outside the skill package')
    old = read_json(root / 'config.json')
    if old:
        config = Config(root)
        if str(workspace) not in config.value.get('workspaces', []):
            raise Conflict('Existing instance preserved; use configure-host to register an additional workspace')
    else:
        value = template()
        value.update(project_name=name, installation_root=str(package), workspaces=[str(workspace)])
        write_json(root / 'config.json', value)
        config = Config(root)
        from .continuity import Continuity
        from .knowledge import Knowledge
        store = Store(config)
        project = config.project_id
        write_json(store.data / 'research-projects.json', dict(schema_version=1, version=1, default_project_id=project,
            branches={'main': project}, projects={project: dict(id=project,name=name,path='研究项目/我的研究',kind='research',
                                                              enabled=True,bm_project=project,goal='')}))
        Continuity(store).bind(workspace, 'instance-initialization', 'main', goal='主要研究线', create=True, project=project)
        Knowledge(store).views()
        from .timeline import publish_projection
        publish_projection(Knowledge(store))
    ensure_vault_identity(config)
    result = dict(state='existing_preserved' if old else 'initialized', root=str(root), package_root=str(package),
                  workspace=str(workspace), automatic_capture='not_verified', obsidian='not_enabled')
    result['host'] = configure_host(config, workspace)
    if with_obsidian:
        result['obsidian'] = attach_obsidian(config)
    return result


def configure_host(config, workspace):
    from .host_config import ensure_mcp_server
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError('Workspace must exist')
    store = Store(config)
    settings = dict(command=sys.executable, args=['-m','research_memory.cli','--root',str(config.root),'research-mcp'],
                    startup_timeout_sec=30)
    # Preflight existing entries before making any host changes.
    path = workspace / '.codex/config.toml'
    text = path.read_text(encoding='utf-8-sig') if path.exists() else ''
    parsed = tomllib.loads(text)
    current = parsed.get('mcp_servers', {}).get('research_memory')
    if current and any(current.get(k) != settings[k] for k in ('command','args')):
        raise Conflict('Existing research_memory MCP configuration preserved: '+str(path))
    hooks_path = workspace / '.codex/hooks.json'
    hooks = read_json(hooks_path, {'hooks': {}})
    hook_script = config.package_root / 'scripts/hook.py'
    # Windows quotes apply to paths only; no user message is ever interpolated here.
    if any('"' in str(p) for p in (sys.executable, hook_script, config.root)):
        raise ValueError('Unsupported quote in hook executable path')
    command = f'"{sys.executable}" "{hook_script}" --root "{config.root}"'
    new_hooks = json.loads(json.dumps(hooks))
    events = ['SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','PostToolUseFailure','Stop','PreCompact','PostCompact','Interrupt','SessionEnd']
    for event in events:
        groups = new_hooks.setdefault('hooks', {}).setdefault(event, [])
        existing = [h for group in groups for h in group.get('hooks', []) if 'scripts/hook.py' in h.get('command','').replace('\\','/')]
        if any(h.get('command') != command for h in existing):
            raise Conflict('Existing research hook preserved: '+str(hooks_path))
        if not existing:
            groups.append({'hooks':[dict(type='command',command=command,timeout=3 if event in {'Interrupt','SessionEnd'} else 15)]})
    with store.lock('installation'):
        for p in (path, hooks_path):
            if p.exists():
                backup = store.data / 'installation-backups' / (file_hash(p)+p.suffix)
                if not backup.exists():
                    atomic(backup,p.read_bytes())
        if not current:
            section = '\n[mcp_servers.research_memory]\n'+''.join(k+' = '+json.dumps(v,ensure_ascii=False)+'\n' for k,v in settings.items())
            candidate = text.rstrip()+'\n'+section
            tomllib.loads(candidate)
            atomic(path,candidate.encode('utf-8'))
        write_json(hooks_path,new_hooks)
        value = read_json(config.path)
        value['workspaces'] = sorted(set(value.get('workspaces',[])+[str(workspace)]))
        write_json(config.path,value)
        write_json(store.data/'installation.json',dict(package_root=str(config.package_root),python=sys.executable,
            state='configured_not_host_verified',at=now(),workspace=str(workspace),
            managed_mcp=settings,hook_command=command))
    return dict(state='configured_not_host_verified', config=str(path), hooks=str(hooks_path))


def attach_obsidian(config, vault=None):
    target = Path(vault).resolve() if vault else config.directory('vault')
    if target != config.directory('vault').resolve():
        raise ValueError('Attach this instance vault; use a separate instance for another vault')
    ensure_vault_identity(config)
    package = config.package_root
    source = package/'tools/obsidian/graph/plugin'
    if not (source/'manifest.json').is_file():
        raise ValueError('Obsidian component is missing from this package')
    store = Store(config)
    target_plugin = target/'.obsidian/plugins/research-graph'
    receipt = read_json(store.data/'obsidian-install.json',{})
    expected = receipt.get('files',{})
    if target_plugin.exists() and not expected:
        raise Conflict('Existing unmanaged plugin preserved; validate and import its installation before upgrading')
    files = [p for p in source.iterdir() if p.is_file() and (p.suffix in {'.js','.json','.css','.txt'} or p.name == 'LICENSE')]
    from .plugin_bundle import bundle_main
    content={p.name:p.read_bytes() for p in files}
    content['main.js']=bundle_main(source)
    from .storage import digest
    hashes={name:digest(raw) for name,raw in content.items()}
    for name in content:
        dest = target_plugin/name
        if dest.exists() and file_hash(dest) not in {expected.get(name), hashes[name]}:
            raise Conflict('Locally modified plugin preserved: '+name)
    with store.lock('installation'):
        backup = store.data/'installation-backups'/('obsidian-'+uuid.uuid4().hex)
        if target_plugin.exists():
            shutil.copytree(target_plugin,backup)
        for name,raw in content.items():
            atomic(target_plugin/name,raw)
        state = read_json(target_plugin/'data.json',{})
        state['backend'] = dict(python=sys.executable,root=str(config.root))
        write_json(target_plugin/'data.json',state)
        enabled = read_json(target/'.obsidian/community-plugins.json',[])
        if 'research-graph' not in enabled:
            enabled.append('research-graph')
        write_json(target/'.obsidian/community-plugins.json',enabled)
        write_json(store.data/'obsidian-install.json',dict(at=now(),files=hashes,backup=str(backup)))
    return dict(state='installed_reload_required',vault=str(target),timeline='available',
                local_graph='Install and enable Juggl 1.5.0 when local graph is needed')


def doctor(config):
    store = Store(config)
    dependencies = {}
    for package in ('research-memory','basic-memory','fastmcp','fastembed','PyYAML','psutil'):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = 'not_installed'
    with store.db() as db:
        counts = dict(events=db.execute('SELECT COUNT(*) FROM events').fetchone()[0],
                      organized=db.execute('SELECT COUNT(*) FROM processed').fetchone()[0])
    return dict(root=str(config.root),package_root=str(config.package_root),workspaces=config.value.get('workspaces',[]),
                python=sys.version,dependencies=dependencies,counts=counts,
                hooks=read_json(store.data/'health/hooks.json',{'state':'not_observed'}),
                installation=read_json(store.data/'installation.json',{'state':'legacy_or_unconfigured'}),
                obsidian=read_json(store.data/'obsidian-install.json',{'state':'not_enabled'}),
                field_evaluation='not_verified',gaps=[read_json(p) for p in (store.data/'gaps').glob('*.json')])


def uninstall(config):
    """Remove only exact managed host entries. Never delete research data or runtime."""
    receipt = read_json(config.directory('data')/'installation.json',{})
    results = []
    for workspace in config.value.get('workspaces',[]):
        path = Path(workspace)/'.codex/config.toml'
        if path.exists():
            import re
            text = path.read_text(encoding='utf-8-sig')
            if tomllib.loads(text).get('mcp_servers',{}).get('research_memory') == receipt.get('managed_mcp'):
                replacement = re.sub(r'(?ms)^\[mcp_servers\.research_memory\]\s*\n.*?(?=^\[|\Z)', '', text)
                tomllib.loads(replacement)
                atomic(path,replacement.encode('utf-8'))
                results.append(str(path))
        hooks_path = Path(workspace)/'.codex/hooks.json'
        if hooks_path.exists():
            hooks = read_json(hooks_path)
            for key, groups in hooks.get('hooks',{}).items():
                for group in groups:
                    group['hooks'] = [h for h in group.get('hooks',[]) if h.get('command') != receipt.get('hook_command')]
                hooks['hooks'][key] = [g for g in groups if g.get('hooks')]
            write_json(hooks_path,hooks)
    return dict(state='host_entries_removed',files=results,data_preserved=str(config.root),
                remaining='Remove the skill directory separately; Obsidian plugin and research data are retained')
