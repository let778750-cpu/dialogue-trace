"""Project-layout migration: isolated construction, hash-checked publication and rollback.

Canonical event/run bytes never enter the write set. The original archive namespace
is unchanged; versioned ownership overlays describe historical research membership.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import uuid
import yaml

from .storage import Config, Store, Conflict, atomic, digest, encode, file_hash, now, read_json, write_json
from .knowledge import Knowledge
from .readability import ViewPaths, clean_name, render_source, rewrite_links, source_title
from .research_projects import ResearchProjects, REGISTRY, OWNERSHIP, SYSTEM, HOME, initial_catalog

DATA_FILES = {REGISTRY, OWNERSHIP, 'registry.json', 'view-paths.json', 'navigation-views.json'}
DATA_DIRS = {'notes', 'source-views', 'view-revisions', 'project-registry-history'}


class StructureMigration:
    def __init__(self, knowledge):
        self.knowledge, self.store = knowledge, knowledge.store
        self.config, self.root, self.vault = self.store.config, self.store.config.root, knowledge.vault

    def prepare(self):
        with self.store.lock('knowledge'), self.store.lock('source-views'), self.store.lock('continuity'):
            if ResearchProjects(self.config).active:
                raise Conflict('Research structure is already active; do not repeat migration')
            identity = 'structure_' + uuid.uuid4().hex
            folder = self.store.data / 'migrations' / identity
            stage = self.config.directory('runtime') / 'structure-staging' / identity
            write_json(stage / 'config.json', self.config.value)
            target = Config(stage)
            notes = self.knowledge.records()
            old_paths = ViewPaths(self.store)
            for note in notes:
                path = self.vault / note['path']
                if not path.is_file() or file_hash(path) != note['published_hash'] or note.get('needs_semantic_reconciliation'):
                    raise Conflict('Review changed note before migration: ' + note['path'])
            sources = set(old_paths.value['sources']) | {s['event_id'] for n in notes for s in n['sources']}
            sources |= {e for n in notes for r in n.get('relations', []) for e in r.get('source_event_ids', [])}
            for event in sources:
                path = self.vault / old_paths.source(event)
                manifest = read_json(self.store.data / 'source-views' / (event + '.json'), {})
                if path.exists() and (not manifest or file_hash(path) != manifest.get('published_hash')):
                    raise Conflict('Review changed source before migration: ' + str(path))

            # Copy a narrow local snapshot. No plug-in secrets, host history or BM DB.
            for name in ('events', 'notes', 'source-views', 'receipts', 'checkpoints'):
                if (self.store.data / name).exists():
                    shutil.copytree(self.store.data / name, target.directory('data') / name, dirs_exist_ok=True)
            for name in ('registry.json', 'view-paths.json'):
                if (self.store.data / name).exists():
                    shutil.copy2(self.store.data / name, target.directory('data') / name)
            shutil.copytree(self.config.directory('runs'), target.directory('runs'), dirs_exist_ok=True)
            for path in self.vault.rglob('*'):
                relative = path.relative_to(self.vault)
                if path.is_file() and not any(p.startswith('.') for p in relative.parts):
                    dest = target.directory('vault') / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
            staged_store = Store(target)
            staged = Knowledge(staged_store)
            events = [read_json(p)['event'] for p in staged_store.events.glob('*.json')]
            intents = [read_json(p) for p in target.directory('runs').glob('*/intent.json')]
            catalog, owners = initial_catalog(self.config, notes, events, intents)
            write_json(staged_store.data / REGISTRY, catalog)
            write_json(staged_store.data / OWNERSHIP, owners)
            write_json(staged_store.data / 'project-registry-history/1.json', catalog)
            projects = ResearchProjects(target)
            registry = read_json(staged_store.data / 'registry.json', {'workspaces': {}, 'sessions': {}, 'branches': {}})
            for w, p in catalog['branches'].items():
                registry['branches'].setdefault(w, {'goal': projects.get(p)['goal'], 'created_at': now()})
                registry['branches'][w]['research_project_id'] = p
            write_json(staged_store.data / 'registry.json', registry)
            paths = ViewPaths(staged_store)
            paths.value = {'schema_version': 2, 'enabled': True, 'notes': {}, 'sources': {}, 'aliases': deepcopy(old_paths.value['aliases'])}
            changes = []
            for note in notes:
                old = note['path'].replace('\\', '/')
                value = deepcopy(note)
                value['research_project_id'] = owners['notes'][note['id']]
                if value['research_project_id'] != projects.default:
                    value['original_workstream_id'] = value['workstream_id']
                    value['workstream_id'] = value['research_project_id'] + '-main'
                new = paths.allocate('note', note['id'], note['title'], value)
                value.update(path=new, view_revision=identity)
                paths.value['aliases'][old] = new
                write_json(staged_store.data / 'notes' / (note['id'] + '.json'), value)
                changes.append({'kind': 'note', 'id': note['id'], 'old': old, 'new': new})
            for event in sorted(sources, key=lambda e: (self.store.get(e)['event'].get('occurred_at') or '', e)):
                old, new = old_paths.source(event), paths.source(event)
                envelope = staged_store.get(event)
                prior = (self.vault / old).read_text(encoding='utf-8') if (self.vault / old).is_file() else ''
                meta = yaml.safe_load(prior.split('---', 2)[1]) if prior.startswith('---\n') else {}
                text, attachments = render_source(staged_store, envelope, new, source_title(envelope), (meta or {}).get('permalink'))
                atomic(staged.vault / new, text.encode('utf-8'))
                for name, content in attachments:
                    atomic(staged.vault / name, content)
                write_json(staged_store.data / 'source-views' / (event + '.json'), {'path': new, 'published_hash': digest(text.encode()), 'title': source_title(envelope)})
                paths.value['aliases'][old] = new
                changes.append({'kind': 'source', 'id': event, 'old': old, 'new': new})
            # Move ancillary content; retain user prose and exact Canvas geometry.
            known = {c['old'] for c in changes}
            main = projects.get()['path']
            for original in sorted(self.vault.rglob('*')):
                rel = original.relative_to(self.vault).as_posix()
                if not original.is_file() or any(p.startswith('.') for p in original.relative_to(self.vault).parts) or rel in known:
                    continue
                if rel == 'Research.md': new = HOME
                elif rel == 'Research.base': new = main + '/研究记录表.base'
                elif rel.startswith('Graphs/'):
                    focus = next((n for n in notes if n['id'] == original.stem), None)
                    new = main + '/图谱/' + clean_name(focus['title'] if focus else original.stem, 60) + '.canvas'
                elif rel.startswith('System/'): new = SYSTEM + '/' + rel[len('System/'):]
                elif rel.startswith('Attachments/'): new = main + '/附件/' + original.name
                elif rel.startswith('projects/routing-acceptance/'):
                    new = projects.get('routing-acceptance', disabled=True)['path'] + '/对话与来源/原路由验收资料/' + original.name
                else:
                    # Unknown files are preserved in an explicit review area, never silently dropped.
                    new = main + '/附件/迁移待分类/' + rel
                paths.value['aliases'][rel] = new
                if rel not in {'Research.md', 'Research.base'}:
                    atomic(staged.vault / new, original.read_bytes())
                changes.append({'kind': 'ancillary', 'old': rel, 'new': new})
            # Flatten aliases from earlier migrations, including already-supported MCP paths.
            for old, destination in list(paths.value['aliases'].items()):
                seen = {old}
                while destination in paths.value['aliases'] and destination not in seen:
                    seen.add(destination); destination = paths.value['aliases'][destination]
                paths.value['aliases'][old] = destination
            paths.save()
            for change in changes:
                if change['old'] != change['new']:
                    (staged.vault / change['old']).unlink(missing_ok=True)
            def rewrite(value):
                if isinstance(value, dict): return {k: rewrite(v) for k, v in value.items()}
                if isinstance(value, list): return [rewrite(v) for v in value]
                if isinstance(value, str): return paths.value['aliases'].get(value, rewrite_links(value, paths.value['aliases']))
                return value
            for file in staged.vault.rglob('*'):
                if file.is_file() and file.suffix in {'.canvas', '.base'}:
                    if file.suffix == '.canvas': write_json(file, rewrite(read_json(file)))
                    else: atomic(file, yaml.safe_dump(rewrite(yaml.safe_load(file.read_text(encoding='utf-8'))), allow_unicode=True).encode())
                elif file.is_file() and file.suffix == '.md' and not '/对话与来源/' in file.as_posix():
                    atomic(file, rewrite_links(file.read_text(encoding='utf-8'), paths.value['aliases']).encode())
            # Publish preliminary note views, then refresh with readable run references.
            for note in staged.records():
                text = staged.render(note, paths).encode()
                note['published_hash'] = digest(text)
                atomic(staged.vault / note['path'], text)
                write_json(staged_store.data / 'notes' / (note['id'] + '.json'), note)
            staged_store.repair()
            result = staged.views()
            if result['view_conflicts']:
                raise Conflict('Staged projection conflict: ' + str(result['view_conflicts']))
            # Navigation run links must point at actual engineering artifacts, not the snapshot.
            navigation = read_json(staged_store.data / 'navigation-views.json', {})
            for rel in navigation:
                file = staged.vault / rel
                content = file.read_text(encoding='utf-8').replace(stage.as_uri(), self.root.as_uri())
                atomic(file, content.encode()); navigation[rel] = file_hash(file)
            write_json(staged_store.data / 'navigation-views.json', navigation)
            operations = []
            candidates = set()
            for root in (self.root, stage):
                c = self.config if root == self.root else target
                for path in c.directory('vault').rglob('*'):
                    if path.is_file() and not any(p.startswith('.') for p in path.relative_to(c.directory('vault')).parts):
                        candidates.add(path.relative_to(root).as_posix())
                for name in DATA_FILES:
                    candidates.add((c.directory('data') / name).relative_to(root).as_posix())
                for name in DATA_DIRS:
                    candidates.update(p.relative_to(root).as_posix() for p in (c.directory('data') / name).rglob('*.json'))
            for rel in sorted(candidates):
                original, proposed = self.root / rel, stage / rel
                before = original.read_bytes() if original.is_file() else None
                after = proposed.read_bytes() if proposed.is_file() else None
                # Existing historical revisions absent from snapshot are retained.
                if not proposed.is_file() and any(rel.startswith('data/' + d + '/') for d in {'view-revisions', 'project-registry-history'}):
                    continue
                if before == after: continue
                op = {'path': rel, 'before': digest(before) if before is not None else None, 'after': digest(after) if after is not None else None}
                for data, key in ((before, 'before'), (after, 'after')):
                    if data is not None: atomic(folder / 'blobs' / op[key], data)
                operations.append(op)
            plan = {'id': identity, 'kind': 'research-structure', 'project_id': self.config.project_id, 'state': 'prepared', 'at': now(),
                    'operations': operations, 'changes': changes, 'staging': stage.relative_to(self.root).as_posix(),
                    'canonical_events_modified': False, 'run_artifacts_modified': False,
                    'event_hashes': {p.name: file_hash(p) for p in self.store.events.glob('*.json')}}
            write_json(folder / 'plan.json', plan)
            return {'plan': (folder / 'plan.json').relative_to(self.root).as_posix(), 'state': 'prepared', 'files': len(operations), 'changes': changes}

    def load(self, path):
        path = self.config.inside(path)
        if not path.is_relative_to(self.store.data / 'migrations') or path.name != 'plan.json':
            raise ValueError('Expected a local migration plan')
        plan = read_json(path)
        if plan.get('kind') != 'research-structure' or plan.get('project_id') != self.config.project_id:
            raise ValueError('Wrong migration type or archive')
        for op in plan['operations']:
            target = self.config.inside(op['path'])
            allowed = target.is_relative_to(self.vault) and not any(p.startswith('.') for p in target.relative_to(self.vault).parts)
            if target.is_relative_to(self.store.data):
                relative = target.relative_to(self.store.data)
                allowed = relative.as_posix() in DATA_FILES or (len(relative.parts) > 1 and relative.parts[0] in DATA_DIRS)
            if not allowed: raise ValueError('Migration write outside view/ownership scope')
            for key in ('before', 'after'):
                code = op[key]
                if code and (len(code) != 64 or any(c not in '0123456789abcdef' for c in code) or file_hash(path.parent / 'blobs' / code) != code):
                    raise ValueError('Migration blob hash mismatch')
        return path, plan

    def apply(self, path, rollback=False):
        with self.store.lock('knowledge'), self.store.lock('source-views'), self.store.lock('continuity'), self.store.lock('research-projects'):
            path, plan = self.load(path)
            allowed = {'applied', 'unknown', 'applying', 'rolling_back'} if rollback else {'prepared'}
            if plan['state'] not in allowed:
                raise Conflict('Inspect incomplete migration; do not automatically replay: ' + plan['state'])
            for op in plan['operations']:
                file = self.config.inside(op['path'])
                actual = file_hash(file) if file.is_file() else None
                if actual not in ({op['before'], op['after']} if rollback else {op['before']}):
                    raise Conflict('File changed after preview; preserved: ' + op['path'])
            for name, code in plan['event_hashes'].items():
                if file_hash(self.store.events / name) != code: raise Conflict('Canonical event changed: ' + name)
            key = 'before' if rollback else 'after'
            plan['state'] = 'rolling_back' if rollback else 'applying'
            write_json(path, plan)
            try:
                for op in sorted(plan['operations'], key=lambda x: x[key] is None):
                    file = self.config.inside(op['path'])
                    if op[key] is None: file.unlink(missing_ok=True)
                    else: atomic(file, (path.parent / 'blobs' / op[key]).read_bytes())
                plan.update(state='rolled_back' if rollback else 'applied', completed_at=now())
            except Exception:
                plan['state'] = 'unknown'; write_json(path, plan); raise
            write_json(path, plan)
        # Catalog is disposable and repair never executes an experiment.
        repair = self.store.repair()
        return {'state': plan['state'], 'plan': path.relative_to(self.root).as_posix(), 'catalog': repair,
                'index': 'requires_project_reconfiguration_and_reindex'}
